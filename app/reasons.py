REASONS = {
    'COLUMN_COUNT':'列数错误', 'MISSING_ID':'编号缺失', 'DUPLICATE_CONFLICT':'重复编号冲突',
    'MISSING_VALUE':'数值缺失', 'BAD_NUMBER':'数值格式错误', 'BAD_TIME':'时间格式错误',
    'BAD_UNIT':'单位不受支持', 'UNKNOWN_REFERENCE':'引用对象不存在', 'INVALID_RANGE':'范围错误',
    'VERSION_CONFLICT':'版本冲突', 'EMPTY_FILE':'空文件', 'BLANK_FILE':'全空行',
    'HEADER_ONLY':'仅有表头', 'STALE_VERSION':'复核版本已更新', 'NOT_FOUND':'批次不存在',
    'BAD_TYPE':'事件类型无效', 'REMINDER_REF':'撤下缺少提醒号', 'REMINDER_NOT_FOUND':'提醒不存在',
    'REMINDER_MEMBER':'撤下会员与提醒不一致', 'VERSION_ROLLBACK':'提醒版本回退',
    'REMINDER_TERMINAL':'提醒已终态不能改版', 'REMINDER_EXPIRED_AT_CREATE':'提醒生成时已到期',
    'HOLD_SQUEEZED':'消费压缩占用', 'HOLD_RESTORED':'退货回补占用', 'HOLD_ALLOCATED':'建立提醒占用',
    'LOT_EXPIRED_SQUEEZE':'批次到期压缩占用', 'SNAPSHOT_DOWNGRADED':'占用挤空降级快照', 'REMINDER_CANCELLED':'撤下释放',
    'REMINDER_EXPIRED':'到期释放', 'RETRY_IDEMPOTENT':'重试幂等不新增占用',
    'RECONCILE_MISMATCH':'占用对账不一致',
}
def reject(state, record, code, detail):
    state['quarantine'].append({'line':record.get('_line',0),'id':record.get('id',''),
       'code':code,'detail':detail,'raw':{k:v for k,v in record.items() if not k.startswith('_')}})
