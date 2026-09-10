# 箱规重量发布清单

1. 暂停旧 API、worker、scheduler 写入，按现有数据库运维流程备份 PostgreSQL，记录备份位置并验证可恢复。初次实现阶段未部署；本地部署记录见下。
2. 部署本次代码后，在项目根执行 `.venv/bin/python scripts/dev.py migrate`。Alembic 由 `48b7a65dc109` 升到 `38b7c4209a61`，新增商品箱规/单重、发货行箱规三个可空字段；不回填未知历史箱规。
3. 执行 `npm --prefix apps/web run build`，按 `docs/local-development.md` 的现有局域网发布流程启动新 API、worker、scheduler 和 Web。
4. 上线核对：商品包装保存、采购零散件数与快捷编辑、发货整箱限制、旧待发单补箱规后发出、已发单按原数量接收。
5. 回退优先恢复旧代码并保留新增的可空字段；若确需数据库回退，先停止新版本写入并备份新增箱规重量数据，再以同一数据库环境执行 `alembic downgrade 48b7a65dc109`。降级将删除新增三列，需从备份恢复新增数据。

无新外部服务、配置密钥、调度任务或队列。重量当前采用每件kg；若业务需每箱重量，应先统一计算口径后再录入。

## 本地部署记录（2026-09-10）

- 用户已授权部署到本地，旧应用停止后完成数据库备份并用 pg_restore 完整解析校验。
- 备份：`/Users/jammy/Documents/develop/SJLERP/.local/backups/20260910-carton-packing-115806/before-packing.dump`（416264字节，权限0600）。
- 前端重新构建通过，`scripts/local.sh start` 已执行迁移并启动 Web、API、worker、scheduler 四个进程。
- 业务库版本 `38b7c4209a61`，三个新增字段在位；部署前后商品34条、采购单1条、发货明细0条一致。
- 本机 `http://127.0.0.1:5173` 与局域网 `http://192.168.31.23:5173` 健康检查、主页及构建资源一致性校验通过；数据库和Redis均ok。
- 运行中API的OpenAPI已包含商品箱规重量字段和单行箱规修改接口。未向业务库插入验收单据。
