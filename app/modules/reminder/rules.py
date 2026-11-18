"""兑换提醒占用（模块 M7）。

提醒占用是独立于积分批次账的意向台账：不扣减任何批次 remaining，不改变财务口径数字。
普通消费永远先按 FEFO 落账（M4），本模块在 M4 产出的积分流水之上推进会员可用余额，
再按 (提醒到期, 生成时刻, 提醒号) 确定性重算占用，因此提醒不会误挡普通消费。
重放为纯函数，同输入同规则版本得到同占用结果。
"""
from app.coerce import instant
from app.errors import BusinessError
from app.reasons import reject

# 同一时刻的处理顺序：先财务动作，后提醒动作；提醒内部先生成后撤下。
PRIORITY = {'EXPIRE': -1, 'EARN': 0, 'SPEND': 1, 'REFUND': 2,
            'REMIND': 3, 'REMIND_OFF': 4}
# 财务流水对会员可用余额的增减方向。
DELTA = {'EARN': 1, 'SPEND': -1, 'REFUND': 1, 'EXPIRE': -1}
ACTIVE = {'HOLD', 'SNAPSHOT'}
TERMINAL = {'CANCELLED', 'EXPIRED'}
# 触发重平衡时，新增占用与压缩占用分别使用的原因码。
INCREASE_REASON = {'EARN': 'HOLD_ALLOCATED', 'REFUND': 'HOLD_RESTORED',
                   'REMIND': 'HOLD_ALLOCATED', 'EXPIRE': 'HOLD_ALLOCATED',
                   'SPEND': 'HOLD_ALLOCATED', 'SETTLE': 'HOLD_RESTORED'}
DECREASE_REASON = {'SPEND': 'HOLD_SQUEEZED', 'EXPIRE': 'LOT_EXPIRED_SQUEEZE',
                   'SETTLE': 'HOLD_SQUEEZED'}


def _entry(reminder, action, points, at, code):
    return {'id': reminder['id'], 'member': reminder['member'], 'action': action,
            'points': points, 'at': at, 'code': code}


def replay_reminders(records, point_ledger, as_of):
    """按时序重放提醒事件。

    records: 经 M1-M5 采信/校验后的事件（失败财务事件已被剔除）。
    point_ledger: M4 的重放结果，ledger 含 EARN/SPEND/REFUND/EXPIRE 流水；
                  REFUND 流水的 points 即实际恢复到未过期批次的积分（过期部分不复活）。
    """
    reminders = {}
    hold_ledger = []
    errors = []
    order = 0
    available = {}   # 会员当前可用（未过期）积分

    def rebalance(member, at, trigger):
        """按确定性顺序把该会员的可用积分分配给活跃提醒，逐条写占用/释放流水。"""
        pool = available.get(member, 0)
        actives = [r for r in reminders.values()
                   if r['member'] == member and r['status'] in ACTIVE]
        actives.sort(key=lambda r: (instant(r['remind_expires']),
                                    instant(r['created_at']), r['id']))
        for r in actives:
            before, granted = r['hold'], min(r['requested'], pool)
            pool -= granted
            r['hold'] = granted
            if granted > before:
                hold_ledger.append(_entry(r, 'HOLD', granted - before, at,
                                          INCREASE_REASON[trigger]))
            elif granted < before:
                hold_ledger.append(_entry(r, 'RELEASE', before - granted, at,
                                          DECREASE_REASON.get(trigger, 'HOLD_SQUEEZED')))
            if granted == r['requested']:
                r['status'] = 'HOLD'
                r['squeezed'] = False
            else:
                if before == r['requested'] and granted < before:
                    r['squeezed'] = True
                r['status'] = 'SNAPSHOT'
                if granted == 0 and before > 0:
                    r['release_code'] = 'SNAPSHOT_DOWNGRADED'

    finance = [(instant(e['at']), e['action'], e) for e in point_ledger['ledger']]
    timeline = sorted(
        finance + [(instant(r['at']), r['type'], r)
                   for r in records if r['type'] in {'REMIND', 'REMIND_OFF'}],
        key=lambda x: (x[0], PRIORITY[x[1]], x[2]['id']))

    for at, kind, row in timeline:
        if kind in DELTA:
            available[row['member']] = available.get(row['member'], 0) \
                + DELTA[kind] * int(row['points'])
            rebalance(row['member'], row['at'], kind)
            continue
        if kind == 'REMIND':
            try:
                amount, version = int(row['points']), int(row['version'])
                expiry = instant(row['expires'])
                key = row.get('ref', '').strip()
                if not key:
                    raise BusinessError('REMINDER_REF', '提醒事件必须在引用列填写提醒号')
                if expiry <= at:
                    raise BusinessError('REMINDER_EXPIRED_AT_CREATE', '提醒生成时已到期')
                existed = reminders.get(key)
                if existed is not None and existed['member'] != row['member']:
                    raise BusinessError('DUPLICATE_CONFLICT', '提醒号被其他会员占用')
                if existed is not None and version < existed['version']:
                    raise BusinessError('VERSION_ROLLBACK', '提醒版本号不得回退')
                if existed is not None and version == existed['version']:
                    # 同提醒同版本重试：幂等，不新增任何占用。
                    existed['retries'] += 1
                    hold_ledger.append(_entry(existed, 'RETRY', 0, row['at'],
                                              'RETRY_IDEMPOTENT'))
                    continue
                if existed is not None and existed['status'] in TERMINAL:
                    raise BusinessError('REMINDER_TERMINAL', '已撤下或到期的提醒不能改版')
                if existed is not None:
                    if existed['hold']:
                        hold_ledger.append(_entry(existed, 'RELEASE', existed['hold'],
                                                  row['at'], 'HOLD_SQUEEZED'))
                    existed.update(requested=amount, remind_expires=expiry.isoformat(),
                                   version=version, hold=0, status='SNAPSHOT',
                                   release_code='', squeezed=False, retries=existed['retries'])
                    target = existed
                else:
                    order += 1
                    target = {'id': key, 'member': row['member'],
                              'requested': amount, 'hold': 0,
                              'remind_expires': expiry.isoformat(),
                              'created_at': row['at'], 'version': version,
                              'status': 'SNAPSHOT', 'release_code': '', 'squeezed': False,
                              'retries': 0, 'order': order}
                    reminders[key] = target
                rebalance(row['member'], row['at'], 'REMIND')
            except BusinessError as exc:
                # 生成失败：仅隔离该事件，已有占用保持旧版结果不变。
                errors.append((row, exc.code, exc.message))
            continue
        # REMIND_OFF：ref 为被撤下的提醒号。
        try:
            key = row.get('ref', '').strip()
            if not key:
                raise BusinessError('REMINDER_REF', '撤下事件必须引用提醒号')
            target = reminders.get(key)
            if target is None:
                raise BusinessError('REMINDER_NOT_FOUND', '撤下引用的提醒不存在')
            if target['member'] != row['member']:
                raise BusinessError('REMINDER_MEMBER', '撤下会员与提醒会员不一致')
            if target['status'] in TERMINAL:
                hold_ledger.append(_entry(target, 'RETRY', 0, row['at'], 'RETRY_IDEMPOTENT'))
                continue
            if target['hold']:
                hold_ledger.append(_entry(target, 'RELEASE', target['hold'],
                                          row['at'], 'REMINDER_CANCELLED'))
            target['hold'] = 0
            target['status'] = 'CANCELLED'
            target['release_code'] = 'REMINDER_CANCELLED'
        except BusinessError as exc:
            errors.append((row, exc.code, exc.message))

    # 结算时点：提醒到期释放（半开区间，到期即失效）；终态提醒不再参与重平衡。
    cutoff = instant(as_of)
    for target in sorted(reminders.values(),
                         key=lambda r: (instant(r['remind_expires']), r['id'])):
        if target['status'] in ACTIVE and instant(target['remind_expires']) <= cutoff:
            if target['hold']:
                hold_ledger.append(_entry(target, 'RELEASE', target['hold'],
                                          as_of, 'REMINDER_EXPIRED'))
            target['hold'] = 0
            target['status'] = 'EXPIRED'
            target['release_code'] = 'REMINDER_EXPIRED'
    for member in tuple(available):
        rebalance(member, as_of, 'SETTLE')

    rows = [_view(r, available.get(r['member'], 0))
            for r in sorted(reminders.values(), key=lambda r: (r['order'], r['id']))]
    return {'rows': rows, 'hold_ledger': hold_ledger, 'errors': errors,
            'check': reconcile(rows)}


def _view(reminder, available_now):
    if reminder['status'] == 'HOLD':
        publish = '压缩待复核' if reminder['squeezed'] else '可发布'
    elif reminder['status'] == 'SNAPSHOT':
        publish = '压缩待复核' if reminder['squeezed'] else '仅快照·余额不足'
    elif reminder['status'] == 'CANCELLED':
        publish = '已撤下'
    else:
        publish = '已到期'
    return {'id': reminder['id'], 'member': reminder['member'],
            'requested': reminder['requested'], 'hold': reminder['hold'],
            'remind_expires': reminder['remind_expires'], 'created_at': reminder['created_at'],
            'version': reminder['version'], 'status': reminder['status'], 'publish': publish,
            'release_code': reminder['release_code'], 'retries': reminder['retries'],
            'squeezed': reminder['squeezed'],
            'available_now': available_now,
            'free_balance': max(available_now - reminder['hold'], 0)}


def reconcile(rows):
    """占用台账对账：任何一条不守恒，整批提醒禁止发布。

    终态（撤下/到期）提醒占用必须为 0；活跃提醒单条与会员合计均不得超过可用。
    """
    issues = []
    grouped = {}
    for row in rows:
        if not 0 <= row['hold'] <= row['requested']:
            issues.append(row['id'])
        if row['status'] in TERMINAL and row['hold'] != 0:
            issues.append(row['id'])
        if row['status'] in ACTIVE and row['hold'] > row['available_now']:
            issues.append(row['id'])
        grouped.setdefault(row['member'], []).append(row)
    for items in grouped.values():
        active = [i for i in items if i['status'] in ACTIVE]
        if sum(i['hold'] for i in active) > items[0]['available_now']:
            issues.extend(i['id'] for i in active)
    issues = sorted(set(issues))
    return {'hold_total': sum(r['hold'] for r in rows),
            'active_reminders': sum(1 for r in rows if r['status'] in ACTIVE),
            'snapshot_reminders': sum(1 for r in rows if r['status'] == 'SNAPSHOT'),
            'released_reminders': sum(1 for r in rows if r['status'] in TERMINAL),
            'balanced': not issues, 'issue_ids': issues}


def apply(state):
    result = replay_reminders(state['records'], state['point_ledger'],
                              state['context']['as_of'])
    for row, code, detail in result['errors']:
        reject(state, row, code, detail)
    check = result['check']
    if not check['balanced']:
        for row in result['rows']:
            if row['id'] in check['issue_ids']:
                row['publish'] = '对账拦截'
                row['release_code'] = 'RECONCILE_MISMATCH'
    state['reminders'] = result['rows']
    state['hold_ledger'] = result['hold_ledger']
    state['reminder_check'] = check
    state['views']['reminder'] = {
        'title': '兑换提醒占用', 'rows': result['rows'],
        'metrics': {'提醒占用': check['hold_total'], '活跃提醒': check['active_reminders'],
                    '快照提醒': check['snapshot_reminders'], '已释放': check['released_reminders'],
                    '对账状态': '一致' if check['balanced'] else '不一致'}}
