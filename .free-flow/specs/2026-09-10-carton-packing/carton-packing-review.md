# 独立评审与修复

独立评审者 packing_review 按 free-review 的规范、业务边界、架构、维护性及资源访问五维只读检查了全部变更和新增文件。

发现并修复两项P2：
- 采购 `Form.useWatch` 默认过滤未注册包装字段：改用 `{ form, preserve: true }`。
- 快捷编辑SKU/中文名后 RemoteSelect 内部旧标签覆盖新标签：新增当前选项受控 `selectedLabel`，采购页传入当前商品行标签，其他调用兼容。

独立复审结论：通过，无新增阻塞问题。浏览器实际验证两项修复生效。本项目未声明整洁清理工具，跳过该步骤。

## 红线自查

| 条目 | 结果及证据 |
|---|---|
| 无循环逐条DB查询 | `apps/api/app/supply/models.py:57` PurchaseLine.product joined relationship；采购selectin行查询同时批量带出商品，无新增逐行请求 |
| 事务与锁顺序 | `apps/api/app/supply/shipments.py:204` 复用locked_shipment采购→货件锁；创建与发出在库存操作前校验箱规 |
| 前端列表与网络有界 | `apps/web/src/SupplyShared.tsx:41` 商品搜索最多30条；快捷编辑仅打开时按id加载一个商品 |
| 前端状态与缓存 | `apps/web/src/PurchasePages.tsx:96` 保留行元数据；`apps/web/src/SupplyShared.tsx:44` 当前标签受控 |
| 包体积边界 | 商品编辑器提取为共享独立模块；沿用页面懒加载，构建成功，主包仍有既有500kB提示 |
| 异常与精度 | API返回可读422/409；前端显示错误；重量使用Decimal和BigInt四位定点运算 |
