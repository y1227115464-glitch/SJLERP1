# 本地上线记录

2026-09-08 16:14（Asia/Shanghai）部署，入口 http://192.168.31.23:5173，原局域网监听和登录来源配置沿用。

1. 独立评审、48 项 PostgreSQL 回归、SQLite 回归、隔离浏览器及迁移升降检查通过。
2. 构建 `.local/reports-web-next`；安装已锁定的 openpyxl、et_xmlfile 和 defusedxml，依赖一致性检查通过。
3. 仅停止项目 PID 文件对应的应用 runner；数据库和 Redis 保持运行。使用 PostgreSQL 14 pg_dump 一致备份、pg_restore --list 核验，备份旧前端。
4. 复制新构建到 apps/web/dist，保留旧散列资源供已打开页面使用。
5. `bash scripts/local.sh start` 增量迁移 9fa3ed5d01d2 → de1aefc77089，新增 report_imports、sales_records、ad_records；启动原 API、worker 和 Web。
6. 实际请求局域网 IP：主页与新报表资源一致，登录、报表权限、五个报表查询、旧采购/货件/库存/商品查询、退出均通过；数据库/Redis 健康为 ok。

备份 `.local/backups/amazon-imports-20260908-161407/` 包含 database.dump、database-contents.txt、manifest.json、web-dist/；目录 700，dump 600。凭据仅从私有本机文件读取，不输出或写入源码。详细验证保存于忽略的 `.local/reports-live-verification.json`。

部署前后数量完全一致：products=34、suppliers=0、supplier_quotes=0、stores=2、users=1，warehouses、purchase_orders/lines、shipments/lines/events、inventory_balances/movements、supply_operations 均 0。新导入批次、销售和广告表均 0，未导入任何合成或真实样本；正式数据由用户在页面选择所属店铺后确认。

## 运维与回退

- `bash scripts/local.sh status` 查看运行状态；stop 停止并保留数据，start 再次启动；日志位于 `.local/logs/`。
- 报表原文件沿用配置的私有文件目录；备份业务数据需同时备份数据库和该目录。
- 页面回退可在停止服务后恢复本次 web-dist 备份；后端回退需恢复匹配旧代码及依赖，新增表与旧模块兼容，保留其业务数据。
- 不对已经导入的正式数据直接执行删除表的 downgrade。需要数据库恢复时先备份现状，在独立数据库恢复验证后安排切换。本次只验证隔离迁移，没有覆盖恢复正式数据库。

后续范围和格式限制见 docs/amazon-report-imports.md。没有自动推送代码或提交原始文件。
