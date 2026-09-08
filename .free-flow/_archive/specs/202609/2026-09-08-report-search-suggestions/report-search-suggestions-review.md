# 独立评审及数据访问核对

2026-09-08，独立只读评审者 report_review 通过，未发现阻断问题；未修改文件，未配置额外整洁清理工具。

评审核实候选继承授权店铺、日期、销售状态和广告粒度；精确 SKU 同时用于列表和摘要。输入草稿与已确认查询分开，候选响应按请求路径绑定，旧响应不会覆盖新候选。已对照当前组件库的键盘事件顺序，候选选择会阻止后续普通关键词提交覆盖。

| 核对项 | 证据 |
|---|---|
| 权限与店铺范围 | reports/routes.py 的 Reader、scope、records_query；test_report_suggestions.py 越权店铺和仓库角色用例 |
| 查询有界、只读投影 | sku_options 只投影 SKU，数据库 DISTINCT 与 LIMIT + 1，默认 50 / 上限 100；沿用店铺 SKU/日期索引，无业务写入 |
| 字面匹配与明细摘要一致 | 候选 icontains(autoescape=True)，sku 等值条件；新增用例验证百分号、大小写、SKU-A 与 SKU-AB |
| 不拉全量、不逐行查库 | 候选一条 SQL，原明细维持服务端分页；没有新增数据循环查询 |
| 请求隔离和操作时机 | ReportSearch 输入防抖与 useResource 路径绑定；只有选择、确认或清除修改已提交条件 |

后端路径相对 apps/api/app/，测试相对 apps/api/tests/，前端相对 apps/web/src/。
