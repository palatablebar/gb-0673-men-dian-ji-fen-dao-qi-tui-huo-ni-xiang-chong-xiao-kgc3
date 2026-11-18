# 深度登记 门店积分到期与退货逆向冲销

规模：中型。使用者：连锁零售会员运营专员。核心规则：消费先用最早到期批次；退款按原消费分配逆向恢复，已过期部分不得复活。

## 功能模块

| 模块 | 使用者动作 | 入口 | 核心文件 | 测试 |
|---|---|---|---|---|
| M1 事件采信 | 执行并复核事件采信 | `POST /api/intake` | `app/modules/intake/rules.py` | `tests/test_intake.py` |
| M2 权益规则 | 执行并复核权益规则 | `POST /api/policy` | `app/modules/policy/rules.py` | `tests/test_policy.py` |
| M3 积分归批 | 执行并复核积分归批 | `POST /api/lots` | `app/modules/lots/rules.py` | `tests/test_lots.py` |
| M4 消费到期 | 执行并复核消费到期 | `POST /api/consumption` | `app/modules/consumption/rules.py` | `tests/test_consumption.py` |
| M5 退货回拨 | 执行并复核退货回拨 | `POST /api/refund` | `app/modules/refund/rules.py` | `tests/test_refund.py` |
| M6 兑换提醒占用 | 执行并复核提醒占用与发布裁决 | `POST /api/reminder` | `app/modules/reminder/rules.py` | `tests/test_reminder.py` |
| M7 余额对账 | 执行并复核余额对账 | `POST /api/reconcile` | `app/modules/reconcile/rules.py` | `tests/test_reconcile.py` |
| M8 期末归档 | 执行并复核期末归档 | `POST /api/archive` | `app/modules/archive/rules.py` | `tests/test_archive.py` |

## 提醒占用陷阱登记

| TRAP | 现象 | 朴素实现 | 本项目处理 | 处理位置 | 测试 |
|---|---|---|---|---|---|
| HOLD-01 | 意向被记成已用积分 | 直接扣批次余额 | 独立意向台账，不写批次账，财务数字不变 | `app/modules/reminder/rules.py` | `tests/test_reminder.py::test_full_hold_publishable` |
| HOLD-02 | 提醒挡死普通消费 | SPEND 前校验占用 | 消费先落账后压缩占用，消费永不因提醒失败 | `app/modules/reminder/rules.py` | `tests/test_reminder.py::test_spend_does_not_block_when_hold_covers_balance` |
| HOLD-03 | 余额不足仍发可兑现提醒 | 按意向额硬占 | 只保留参考快照，占用按可用封顶，禁发布 | `app/modules/reminder/rules.py` | `tests/test_reminder.py::test_insufficient_is_snapshot_only` |
| HOLD-04 | 重试重复占用 | 每次生成新占用 | 同提醒号同版本幂等，仅记 RETRY 流水 | `app/modules/reminder/rules.py` | `tests/test_reminder.py::test_retry_idempotent_no_new_hold` |
| HOLD-05 | 失败生成污染旧占用 | 失败也覆盖状态 | 失败事件只隔离，旧占用保持不变 | `app/modules/reminder/rules.py` | `tests/test_reminder.py::test_failed_generation_keeps_previous_hold` |
| HOLD-06 | 退货后份额不回补 | 占用一次定死 | 退款恢复后按确定性顺序回补 | `app/modules/reminder/rules.py` | `tests/test_reminder.py::test_refund_after_squeeze_refills_in_deterministic_order` |
| HOLD-07 | 撤下/到期不释放 | 占用悬挂 | 撤下与到期均释放并附原因码 | `app/modules/reminder/rules.py` | `tests/test_reminder.py::test_cancel_releases` / `test_expiry_releases` |
| HOLD-08 | 过期积分被占用 | 只看总额不看过期 | 占用只落在未过期可用上，批次到期即压缩 | `app/modules/reminder/rules.py` | `tests/test_reminder.py::test_expired_lot_points_cannot_be_held` |
| HOLD-09 | 占用对账不一致仍发布 | 无守恒闸门 | 单条与会员级双重守恒，不一致拦截发布与归档 | `app/modules/reminder/rules.py`、`app/modules/archive/rules.py` | `tests/test_reminder.py::test_reconcile_blocks_publish`、`tests/test_archive.py::test_reminder_mismatch_blocks` |

## 陷阱登记

| TRAP | 现象 | 朴素实现 | 本项目处理 | 处理位置 | 测试 |
|---|---|---|---|---|---|
| TRAP-01 | GB18030权益中文 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/intake/rules.py` | `tests/test_intake.py::test_gb18030_real` |
| TRAP-02 | BOM表头 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/intake/rules.py` | `tests/test_intake.py::test_bom_real` |
| TRAP-08 | 会员前导零 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/intake/rules.py` | `tests/test_intake.py::test_member_leading_zero` |
| TRAP-04 | 重复表头 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/intake/rules.py` | `tests/test_intake.py::test_repeated_header` |
| TRAP-05 | 缺列记录 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/intake/rules.py` | `tests/test_intake.py::test_column_bad` |
| TRAP-14 | 编号冲突 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/intake/rules.py` | `tests/test_intake.py::test_duplicate_conflict` |
| TRAP-18 | 空态 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/intake/rules.py` | `tests/test_intake.py::test_empty_three` |
| TRAP-07 | 哨兵 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/policy/rules.py` | `tests/test_policy.py::test_sentinel_real` |
| TRAP-11 | UTC归一 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/policy/rules.py` | `tests/test_policy.py::test_utc_real` |
| TRAP-06 | 全角积分 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/policy/rules.py` | `tests/test_policy.py::test_fullwidth_points` |
| TRAP-23 | 权益半开窗 | 静默错算或证据丢失 | 以可复核规则显式处理 | `app/modules/policy/rules.py` | `tests/test_policy.py::test_rule_end_exclusive` |

## 对账规则

原始逻辑输入=采纳行+隔离行+空行+重复表头+同值重复。业务计算按 DATA-DICTIONARY.md 分别核验，不能把上级与下级重复加总。所有隔离保留编号、原值、原始行号和稳定原因码。

## 已知不覆盖

数据来自仓内样例或用户粘贴文件，不连接外部业务生产系统。平台不执行实际资金划转或行政审批。兑换提醒模块只产出占用台账与发布裁决，不展开营销触达（短信/推送/站内信）、优惠券或其他权益活动。
