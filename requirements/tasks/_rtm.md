# 待办需求与验证映射

| 需求 | 主要实现 | 验证 |
|---|---|---|
| 人的事项、权限、版本和幂等 | tasks/models.py common.py routes.py | test_tasks.py / test_task_concurrency.py |
| 时区、全天、下一周一 | tasks/dates.py schemas.py | test_task_dates.py |
| 周期、暂停、补齐、模板页面 | tasks/rules.py scheduler.py | test_task_scheduler.py |
| 改期、实际下单、分批发货、异常恢复 | tasks/events.py sources.py，supply路由 | test_task_scheduler.py / test_task_concurrency.py / test_supply.py |
| 通知委派与撤权 | tasks/scheduler.py TaskNotice，app/routes.py | test_task_scheduler.py |
| 工作台及单据入口 | WorkspacePage / TaskShared / TaskRules，PurchasePages / ShipmentPages | W0浏览器验收记录 |

文件均相对于`apps/api/app`、`apps/api/tests`或`apps/web/src`；使用口径见 [reminders.md](reminders.md)。
