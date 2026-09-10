---
status: pass
reviewed_at: 2026-09-10
---

# 独立评审

评审者：review_fba_defaults 子代理，按 free-review 只读检查。

首次发现：移除仓库选择后，既有非默认仓余额无法通过 UI 定向调整。
修复：余额行新增「调整」，自动携带原店铺、商品和隐藏仓库 ID，店铺、商品锁定；顶部入口继续默认 FBA。
复查：原问题已修复，未发现新增确定问题。未配置额外整洁工具。

## 红线自查

| 项目 | 证据 |
|---|---|
| 默认查找有界，无循环查库 | apps/api/app/supply/defaults.py:16，limit(1)，无循环 |
| 并发建仓使用唯一键 | apps/api/app/supply/defaults.py:20，按 code 冲突忽略；PostgreSQL 并发测试通过 |
| 幂等、库存与建仓同事务 | apps/api/app/supply/inventory.py:126，先声明 operation 再选仓及过账；失败回滚测试通过 |
| 查询保持店铺范围与分页 | apps/api/app/supply/inventory.py:87，复用 scoped/stock_query/paginated |
| 前端无新增监听/effect，列表分页 | apps/web/src/InventoryPages.tsx:15、29，复用 usePagedList |
| 不为默认仓增加前端请求 | apps/web/src/ShipmentForms.tsx:43、InventoryPages.tsx:89，固定文本，后端解析 |
