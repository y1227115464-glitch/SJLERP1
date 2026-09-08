# 局域网更新

2026-09-08 16:45，入口 http://192.168.31.23:5173。

独立评审、54 项 PostgreSQL 测试、SQLite、前端构建、隔离迁移与浏览器确认覆盖通过后，仅停止当前项目 runner，保留 PostgreSQL/Redis，备份数据库和旧前端至 `.local/backups/ad-daily-20260908-164539/`。目录 700、database.dump 600，pg_restore --list 校验通过。

复制 `.local/ad-daily-web-next` 构建到 apps/web/dist 并保留旧散列资源，执行 `bash scripts/local.sh start`，迁移 de1aefc77089 → 2c638fa481b9。新增 report_date、日报身份约束与索引；旧单日去重及重编码，原批次保留，多日汇总保留为历史区间。

正式实例升级前后：商品 34、销售记录 354、导入批次 1、店铺 2、用户 1，供应商/报价、采购/货件/库存及广告均 0，数量一致。新旧 11 个查询、首页、报表静态资源、管理员登录与退出、数据库和 Redis 健康检查通过。证据 `.local/ad-daily-live-verification.json`。未向正式库写入合成或原始样本。

状态命令 `bash scripts/local.sh status`，日志 `.local/logs/`。回退需先停止写入并备份现状，恢复匹配代码与前端；日报合并不会通过 downgrade 恢复被替代的事实，请通过源批次核对，必要时在独立库从备份恢复后安排切换，不覆盖当前正式库。

代码与部署已完成；新版原附件读取受 macOS 限制，待可读取的文件副本补充原样验证。未自动提交或推送代码。
