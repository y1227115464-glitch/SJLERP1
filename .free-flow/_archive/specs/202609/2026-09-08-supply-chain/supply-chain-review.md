# 独立评审与修复

日期：2026-09-08。评审者：独立只读代理 supply_review；实现者与评审者分离。

首轮发现两项 P2：采购取消遇到任何物流分配就拒绝，未满足只取消未分配余量；发出/取消计划缺少请求编号，成功后的网络重试返回冲突。另建议采购选择器只显示可安排的采购单。

修复后复核通过，无阻断问题：取消仅扣未分配量；保留待发/在途及后续接收，收齐后状态正确；发出/取消接入请求幂等，前端保持操作 token；选择器过滤草稿、结束及无余量采购单。PostgreSQL 插入判定改为 RETURNING；聚合数量转整数；SQLite 无时区时间补 UTC，保留 PostgreSQL 原时区。测试验证时间具有有效时区，允许 PostgreSQL 返回 +08:00。

没有配置额外整洁清理工具。已检查 diff 空白、依赖边界与改动范围；保留此前本地部署改动，不提交凭据或测试数据。

## 红线核对

| 要求 | 证据 |
|---|---|
| 店铺范围与敏感金额 | app/supply/common.py:16、24、99；test_supply.py:64、150 |
| 不允许负库存或侵占占用 | app/supply/models.py:110；app/supply/stock.py:22；test_supply.py:120 |
| 事务过账、流水不可编辑 | app/supply/stock.py:22；app/supply/shipments.py:98、152；无流水写改删路由 |
| 重试和并发不重复扣加 | app/supply/common.py:65、70、133；test_supply.py:174、239 |
| 无逐行数据库循环 | stock.py 批量查、批量占用及有序锁；单据最多 100 行，关联 selectin/joined |
| 分页与查询有界 | purchases.py:35；shipments.py:21；inventory.py:77、96；事件最近 200 条 |
| 数据库约束和索引 | app/supply/models.py；迁移 9fa3ed5d01d2；SQLite/PostgreSQL 全套迁移测试 |
| 金额定点、数量整数 | app/supply/schemas.py；common.py:99；test_supply.py:64、210 |
| 切店卸载旧页面 | apps/web/src/App.tsx:124 |
| 局域网 HTTP 请求编号可用 | apps/web/src/SupplyShared.tsx:26 使用 getRandomValues；浏览器建单通过 |

API 路径相对 apps/api/；前端路径相对仓库根目录。详细执行证据见同目录 supply-chain-verification.md。
