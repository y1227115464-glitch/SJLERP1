# 交付验收

2026-09-08，独立评审通过后执行。

- PostgreSQL 14.18 隔离 schema：35 passed，11.58 秒，包含既有功能与两个 PostgreSQL 并发用例。
- SQLite：33 passed、2 skipped；跳过的两个用例依赖 PostgreSQL 行锁，已由上述 PostgreSQL 运行覆盖。
- 前端 `tsc -b && vite build --outDir ../../.local/web-next`：通过。仍有既有主包大于 500 kB 的构建提示。
- `git diff --check`：通过。
- 依赖提供两个 TestClient 弃用警告；本次不变更依赖。

## 契约证据

| 规格契约 | 执行证据 | 结果 |
|---|---|---|
| 采购编辑、金额、输入约束 | test_purchase_validation_money_edit_and_scope / test_draft_edit_rollback_and_receipt_boundaries；浏览器 100 × 3.1234 = 312.3400 | 通过 |
| 分批分配与取消 | test_allocations_cancellation_and_negative_inventory / test_unallocated_cancel_and_dispatch_cancel_replay | 通过 |
| 收发货数量守恒 | test_purchase_shipping_receipts_reservations_and_ledger；浏览器两段完整流程 | 通过 |
| 幂等与并发 | test_postgres_concurrent_allocations_and_receipts：库存 10，两单各占 7，仅一单成功；同 token 收货只记一次，不同 token 不超收 | 通过 |
| 库存调整、不可改流水 | test_warehouse_opening_tracking_and_store_isolation / test_allocations_cancellation_and_negative_inventory；路由只读流水 | 通过 |
| 权限与金额隐藏 | 授权店铺、无店铺、跨店铺详情/写入/摘要、仓库成本隐藏测试 | 通过 |
| 页面和状态 | 三个入口；采购提交、两段发货、分批接收、Shipment ID、物流备注、余额/流水实测；页面布局截图检查 | 通过 |
| 迁移和局域网 | 两种数据库迁移随 tests fixture；正式部署验证见 release 文件 | 见上线记录 |

浏览器使用隔离 SQLite 与合成商品、供应商、仓库、店铺，未写入正式库。实测采购 100，供应商货件 60 接收 40，国内仓再发 25，FBA 接收 20：国内仓 15、FBA 20、仓内合计 35、占用 0、在途合计 25（供应商 20 + FBA 5）；库存流水和本地时间显示正确。

真实用户验收不在此冒充完成；上述为自动测试与代理浏览器操作。FBA 实时快照、销售扣库及 M5/M6 的剩余范围见 docs/supply-chain.md。
