# 本地上线记录

2026-09-08 12:44（Asia/Shanghai）完成，沿用 http://192.168.31.23:5173。

## 发布过程

1. 完成独立评审、SQLite/PostgreSQL 回归及隔离浏览器两段物流验收。
2. `cd apps/web && PATH="$PWD/../../.local/bin:$PATH" npm run build -- --outDir ../../.local/web-next` 生成部署产物。
3. 对本项目 PID 文件确认的 runner 发 TERM，等待 API/worker/Web 退出，数据库与队列继续运行。
4. PostgreSQL 14 `pg_dump --format=custom` 完成一致备份，`pg_restore --list` 验证目录；数据库连接仅从本机 .env 读取，密码不写进命令参数或文档。
5. 保存旧前端构建；复制已验证的新构建到 apps/web/dist。保留旧散列资源，避免已打开页面在刷新前请求资源失败。
6. `bash scripts/local.sh start` 增量迁移 cac0e1679f69 → 9fa3ed5d01d2，后台启动 API、worker 与监听 0.0.0.0:5173 的 Web。
7. 从本机请求局域网 IP：主页与 9 个相关查询接口均 200；管理员登录、权限与退出成功；数据库/Redis 健康状态均 ok。

备份目录：`.local/backups/supply-chain-20260908-124438/`，目录权限 700，database.dump 权限 600；含 database.dump、database-contents.txt、manifest.json、web-dist/。未纳入版本控制。

部署前后核对：当前正式实例 products=0、suppliers=0、supplier_quotes=0、stores=2、users=1，数量全部不变；与早期文档记载的商品导入验证属于不同运行状态。本轮没有导入合成商品或采购记录。新采购/发货/仓库/库存表均空。详细证据：`.local/supply-live-verification.json`。

## 运维和回退

- 查看状态：`bash scripts/local.sh status`。
- 停止：`bash scripts/local.sh stop`；启动：`bash scripts/local.sh start`。
- 业务日志位于 `.local/logs/`，数据库及附件仍沿用既有持久目录。
- 若需要回退页面，先停止服务，将本备份 web-dist/ 复制回 apps/web/dist，再启动。新增数据库表与旧页面兼容，应保留新增业务数据。
- 后端回退需恢复匹配的旧代码版本并保留新增表；不要对已经写入业务数据的库直接 downgrade 或覆盖恢复。若确需数据库恢复，先备份现状、停止写入，恢复到独立数据库核对，再安排切换；本次未执行恢复或删除迁移。

范围：人工采购、物流和库存账已交付。FBA 快照、销售扣库、审批应付、质检退货、装箱和成本分摊继续按计划推进。
