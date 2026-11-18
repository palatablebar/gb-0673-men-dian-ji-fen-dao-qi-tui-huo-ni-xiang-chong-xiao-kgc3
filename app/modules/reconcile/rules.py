def reconcile(state):
    l=state['point_ledger'];issued=sum(r['issued'] for r in l['lots']);remaining=sum(r['remaining'] for r in l['lots']);spent=sum(r['points'] for r in l['spends']);refunded=sum(r['points'] for r in l['refunds']);expired=l['expired']+sum(r['expired_refund'] for r in l['refunds'])
    c=state['counts'];explained=len(state['records'])+len(state['quarantine'])+c['blank']+c['duplicate']+c['repeated_header']
    # 坏列记录只进隔离、不进采信，公式按一行一次去重。
    bad_columns=sum(1 for q in state['quarantine'] if q['code']=='COLUMN_COUNT')
    explained-=bad_columns
    balance={'input':c['input'],'accepted':len(state['records']),'quarantined':len(state['quarantine']),'row_balanced':c['input']==explained,'issued':issued,'remaining':remaining,'spent':spent,'refunded':refunded,'expired':expired,'points_balanced':issued==remaining+spent-refunded+expired}
    # 提醒占用对账（模块7先于归档运行；未运行时不阻断旧入口）。
    rc=state.get('reminder_check')
    if rc is not None:
        balance['reminder_hold']=rc['hold_total'];balance['reminder_balanced']=rc['balanced'];balance['reminder_issues']=rc['issue_ids']
    else:
        balance['reminder_hold']=0;balance['reminder_balanced']=True;balance['reminder_issues']=[]
    return balance
def apply(state):
    state['balance']=reconcile(state);state['views']['reconcile']={'title':'积分余额对账','rows':[state['balance']],'metrics':{'发放':state['balance']['issued'],'净消费':state['balance']['spent']-state['balance']['refunded'],'到期':state['balance']['expired'],'提醒占用':state['balance']['reminder_hold']}}
