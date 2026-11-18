"""兑换提醒占用（M7）专项测试。

覆盖 ADR(docs/REMINDER-HOLD.md) 的全部裁决：
可兑现才占用/不足仅快照、消费不被误挡且压缩占用、退货回补、对账拦截、
生成失败保留旧占用、重试幂等、撤下/到期释放、过期积分不可用。
"""
from copy import deepcopy
from app.engine import evaluate
from app.modules.reminder.rules import replay_reminders, reconcile


def _by_id(sample, key):
    return next(r for r in sample['reminders'] if r['id'] == key)


def _ledger(sample, key):
    return [e for e in sample['hold_ledger'] if e['id'] == key]


# ---------- 样例级裁决 ----------

def test_full_hold_publishable(clean):
    # 可全额兑现 → 建立全额占用（RM31 撤下前为 50/50）；占用不改变财务余额。
    assert any(e['id'] == 'RM31' and e['action'] == 'HOLD' and e['points'] == 50
               for e in clean['hold_ledger'])
    assert clean['balance']['remaining'] == 1010
    # 合成一个结算时仍全额占用的可发布提醒。
    records = _records('M9', [
        {'id': 'E1', 'type': 'EARN', 'points': 100, 'at': '2026-10-01T09:00:00+08:00'},
        {'id': 'H1', 'type': 'REMIND', 'points': 40, 'at': '2026-10-02T09:00:00+08:00',
         'expires': '2026-12-20T00:00:00+08:00', 'ref': 'R9'},
    ])
    out = _ledger_result(records, [])
    assert out['rows'][0]['hold'] == 40 and out['rows'][0]['publish'] == '可发布'


def test_insufficient_is_snapshot_only(clean):
    # 余额不足全额兑现 → 只保留参考快照，占用按可用额封顶。
    r = _by_id(clean, 'RM3')
    assert r['requested'] == 90 and r['hold'] == 70 and r['status'] == 'SNAPSHOT'
    assert r['publish'] == '仅快照·余额不足' and r['free_balance'] == 0


def test_spend_never_blocked_but_squeezes_hold(sample):
    # 普通消费照常落账（S2=50 成功），提醒被压缩且给出释放原因。
    assert any(x['id'] == 'S2' for x in sample['point_ledger']['spends'])
    rm1 = _by_id(sample, 'RM1')
    assert rm1['hold'] == 30 and rm1['publish'] == '压缩待复核'
    assert any(e['action'] == 'RELEASE' and e['code'] == 'HOLD_SQUEEZED'
               for e in _ledger(sample, 'RM1'))


def test_refund_restores_hold(sample):
    # 退货回拨后活跃提醒按序补占用（RM3：60 → 70）。
    rm3 = _by_id(sample, 'RM3')
    assert rm3['hold'] == 70
    assert any(e['code'] == 'HOLD_RESTORED' for e in _ledger(sample, 'RM3'))


def test_retry_idempotent_no_new_hold(sample):
    # 同提醒同版本重试：retries 累计，占用不变，仅留幂等流水。
    rm1 = _by_id(sample, 'RM1')
    assert rm1['retries'] == 1
    retries = [e for e in _ledger(sample, 'RM1') if e['code'] == 'RETRY_IDEMPOTENT']
    assert len(retries) == 1 and retries[0]['points'] == 0


def test_cancel_releases(sample):
    r = _by_id(sample, 'RM31')
    assert r['status'] == 'CANCELLED' and r['hold'] == 0
    assert r['release_code'] == 'REMINDER_CANCELLED' and r['publish'] == '已撤下'


def test_expiry_releases(sample):
    r = _by_id(sample, 'RM41')
    assert r['status'] == 'EXPIRED' and r['hold'] == 0
    assert r['release_code'] == 'REMINDER_EXPIRED'


def test_failed_generation_keeps_previous_hold(sample):
    # BRM1 生成时已到期 → 隔离，且不产生任何提醒记录。
    bad = next(q for q in sample['quarantine'] if q['id'] == 'BRM1')
    assert bad['code'] == 'REMINDER_EXPIRED_AT_CREATE'
    assert all(r['id'] != 'BRM' for r in sample['reminders'])
    # 失败前后占用台账守恒，未被失败事件污染。
    assert sample['reminder_check']['balanced'] is True


def test_bad_version_quarantined(sample):
    assert any(q['id'] == 'BRM2' and q['code'] == 'INVALID_RANGE'
               for q in sample['quarantine'])


def test_reconcile_blocks_publish(sample):
    rows = deepcopy(sample['reminders'])
    rows[0]['hold'] = rows[0]['requested'] + 1
    check = reconcile(rows)
    assert check['balanced'] is False and rows[0]['id'] in check['issue_ids']


def test_hold_never_exceeds_available(sample):
    for member in {r['member'] for r in sample['reminders']}:
        items = [r for r in sample['reminders'] if r['member'] == member]
        assert sum(i['hold'] for i in items) <= items[0]['available_now']
        for i in items:
            assert 0 <= i['hold'] <= i['requested']


# ---------- 合成事件级规则（不依赖样例布局） ----------

def _records(member, rows):
    base = {'member': member, 'rule': '常规', 'ref': '', '_line': 1, 'version': 1}
    return [dict(base, **row) for row in rows]


def _ledger_result(records, lots, as_of='2026-11-30T00:00:00+08:00'):
    point_ledger = {'ledger': [], 'lots': lots, 'spends': [], 'refunds': []}
    # 直接构造与 M4 同构的流水。
    for row in records:
        if row['type'] in {'EARN', 'SPEND', 'REFUND', 'EXPIRE'}:
            point_ledger['ledger'].append(
                {'id': row['id'], 'member': row['member'], 'action': row['type'],
                 'points': row['points'], 'at': row['at']})
    return replay_reminders(records, point_ledger, as_of)


def test_spend_does_not_block_when_hold_covers_balance():
    # 会员 100 分，提醒占用 80；再消费 90 必须成功，提醒被压缩到 10。
    records = _records('M1', [
        {'id': 'E1', 'type': 'EARN', 'points': 100, 'at': '2026-10-01T09:00:00+08:00'},
        {'id': 'H1', 'type': 'REMIND', 'points': 80, 'at': '2026-10-02T09:00:00+08:00',
         'expires': '2026-12-20T00:00:00+08:00', 'ref': 'R1'},
        {'id': 'S1', 'type': 'SPEND', 'points': 90, 'at': '2026-10-03T09:00:00+08:00'},
    ])
    out = _ledger_result(records, [])
    r = next(x for x in out['rows'] if x['id'] == 'R1')
    assert r['hold'] == 10 and r['squeezed'] is True and r['publish'] == '压缩待复核'
    assert r['available_now'] == 10


def test_refund_after_squeeze_refills_in_deterministic_order():
    records = _records('M1', [
        {'id': 'E1', 'type': 'EARN', 'points': 100, 'at': '2026-10-01T09:00:00+08:00'},
        {'id': 'H1', 'type': 'REMIND', 'points': 60, 'at': '2026-10-02T09:00:00+08:00',
         'expires': '2026-12-10T00:00:00+08:00', 'ref': 'R1'},
        {'id': 'H2', 'type': 'REMIND', 'points': 60, 'at': '2026-10-02T10:00:00+08:00',
         'expires': '2026-12-20T00:00:00+08:00', 'ref': 'R2'},
        {'id': 'S1', 'type': 'SPEND', 'points': 60, 'at': '2026-10-03T09:00:00+08:00'},
        {'id': 'B1', 'type': 'REFUND', 'points': 30, 'at': '2026-10-04T09:00:00+08:00'},
    ])
    out = _ledger_result(records, [])
    holds = {x['id']: x['hold'] for x in out['rows']}
    # 到期早的 R1 先回补：R1=60，R2=10。
    assert holds == {'R1': 60, 'R2': 10}


def test_expired_lot_points_cannot_be_held():
    # 积分 100 在 11-01 过期；提醒 10-20 生成、12-01 才到期 → 结算时占用归零。
    records = _records('M1', [
        {'id': 'E1', 'type': 'EARN', 'points': 100, 'at': '2026-10-01T09:00:00+08:00'},
        {'id': 'X1', 'type': 'EXPIRE', 'points': 100, 'at': '2026-11-01T00:00:00+08:00'},
        {'id': 'H1', 'type': 'REMIND', 'points': 40, 'at': '2026-10-20T09:00:00+08:00',
         'expires': '2026-12-01T00:00:00+08:00', 'ref': 'R1'},
    ])
    out = _ledger_result(records, [])
    r = out['rows'][0]
    assert r['hold'] == 0 and r['available_now'] == 0
    assert any(e['code'] == 'LOT_EXPIRED_SQUEEZE' for e in out['hold_ledger'])


def test_remind_off_unknown_ref_rejected_and_holds_intact():
    records = _records('M1', [
        {'id': 'E1', 'type': 'EARN', 'points': 100, 'at': '2026-10-01T09:00:00+08:00'},
        {'id': 'H1', 'type': 'REMIND', 'points': 50, 'at': '2026-10-02T09:00:00+08:00',
         'expires': '2026-12-20T00:00:00+08:00', 'ref': 'R1'},
        {'id': 'O1', 'type': 'REMIND_OFF', 'points': 0,
         'at': '2026-10-03T09:00:00+08:00', 'ref': 'NOPE'},
    ])
    out = _ledger_result(records, [])
    assert out['errors'][0][1] == 'REMINDER_NOT_FOUND'
    assert out['rows'][0]['hold'] == 50 and out['rows'][0]['status'] == 'HOLD'


def test_version_rollback_rejected():
    records = _records('M1', [
        {'id': 'E1', 'type': 'EARN', 'points': 100, 'at': '2026-10-01T09:00:00+08:00'},
        {'id': 'H1', 'type': 'REMIND', 'points': 50, 'at': '2026-10-02T09:00:00+08:00',
         'expires': '2026-12-20T00:00:00+08:00', 'ref': 'R1', 'version': 2},
        {'id': 'H2', 'type': 'REMIND', 'points': 50, 'at': '2026-10-03T09:00:00+08:00',
         'expires': '2026-12-20T00:00:00+08:00', 'ref': 'R1', 'version': 1},
    ])
    out = _ledger_result(records, [])
    assert out['errors'][0][1] == 'VERSION_ROLLBACK'
    assert out['rows'][0]['version'] == 2 and out['rows'][0]['hold'] == 50


def test_deterministic_order_invariant(sample):
    # 乱序输入与顺序输入得到相同占用结果。
    a = replay_reminders(sample['records'], sample['point_ledger'], sample['context']['as_of'])
    shuffled = list(reversed(sample['records']))
    b = replay_reminders(shuffled, sample['point_ledger'], sample['context']['as_of'])
    assert [(r['id'], r['hold'], r['status']) for r in a['rows']] == \
           [(r['id'], r['hold'], r['status']) for r in b['rows']]


def test_terminal_rows_hold_zero(sample):
    for r in sample['reminders']:
        if r['status'] in ('CANCELLED', 'EXPIRED'):
            assert r['hold'] == 0 and r['release_code']


def test_revision_redecides_reminder():
    # 版本提升按改版处理：旧占用先释放，再按新意向额重新裁决。
    records = _records('M1', [
        {'id': 'E1', 'type': 'EARN', 'points': 100, 'at': '2026-10-01T09:00:00+08:00'},
        {'id': 'H1', 'type': 'REMIND', 'points': 80, 'at': '2026-10-02T09:00:00+08:00',
         'expires': '2026-12-20T00:00:00+08:00', 'ref': 'R1', 'version': 1},
        {'id': 'H2', 'type': 'REMIND', 'points': 40, 'at': '2026-10-05T09:00:00+08:00',
         'expires': '2026-12-20T00:00:00+08:00', 'ref': 'R1', 'version': 2},
    ])
    out = _ledger_result(records, [])
    r = out['rows'][0]
    assert r['version'] == 2 and r['requested'] == 40 and r['hold'] == 40
    assert any(e['action'] == 'RELEASE' and e['points'] == 80 for e in out['hold_ledger'])


def test_reason_codes_are_known(sample):
    from app.reasons import REASONS
    for e in sample['hold_ledger']:
        assert e['code'] in REASONS
