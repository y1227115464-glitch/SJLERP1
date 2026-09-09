---
doc_type: release
slug: weekly-operations
stack: mixed
status: shipped
---

# W0 发布物料

发布应用：`apps/api` 的待办 API、规则、通知权限、采购/货件字段与事务事件；`apps/web` 的工作台与相关详情；`scripts/dev.py` 同时托管 API、RQ worker、scheduler 和 Web。

数据库：Alembic `2c638fa481b9 → 48b7a65dc109`。新增7张任务/规则/记录表及索引，采购新增预计发货日和登记下单时间，货件新增预计发货日，通知新增任务关联。旧单据字段为NULL，不做历史提醒回填。已在PostgreSQL隔离schema完成升级、结构检查、回退、再升级及旧档案保留测试。

发布执行顺序：

1. 对本地 PostgreSQL 主业务 public schema 做自包含备份，验证备份清单可读取；保留当前构建和原提交源码归档。记录核心表行数供前后核对。
2. 停止旧应用进程，保留数据库服务；使用已验证的前端构建替换 `apps/web/dist`。
3. 运行 `.venv/bin/python scripts/dev.py migrate`；确认迁移版本及业务行数。
4. `bash scripts/local.sh start` 启动新API、worker、scheduler、Web，保留原局域网入口和`.env`。
5. 检查 `/health/ready`、各进程和scheduler日志；只读确认待办表可查询且没有自动为用户启用规则。

独立调度：`app.tasks.worker`，每10秒一轮；单事件保存点和退避，周期游标与投递版本幂等。规则通过ERP配置，无额外系统cron；不创建Codex自动化。无Apollo、Mongo、外部服务或新增环境变量。

接口：`/api/v1/tasks`（列表、新建、聚合、详情、调整、状态、负责人查询、应用规则），`/api/v1/task-rules`（列表、新建、模板、编辑/暂停）；采购新增`/{id}/schedule`与`/{id}/production`。所有写入沿用登录、CSRF及店铺权限，任务状态和新建有请求幂等，编辑有版本冲突校验。

回滚：优先停止scheduler、恢复旧API与旧前端构建，保留增量表避免丢失新建待办。必须清理增量schema时，先额外备份升级后数据库，再在停写窗口运行`alembic downgrade 2c638fa481b9`；这会删除待办/规则数据，不作为默认回滚步骤。数据库备份恢复应使用隔离库验证后再切换，不直接覆盖运行中的业务库。


发布结果：2026-09-09 已更新原局域网服务。备份位置`.local/backups/w0-20260909T091258Z/`；迁移48b7a65dc109，业务行数与停写备份一致；API/数据库/Redis健康，独立scheduler运行且日志无错误。规则和任务初始为空，由用户启用。
