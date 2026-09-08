# 独立评审与修复

日期：2026-09-08。评审者为独立只读代理 report_review，实现与评审分离；修复后独立复核结论为 PASS，无阻断问题。

首轮发现及修复：

1. 广告同值批次确认只跳过指标，没有更新版本时间，导致更早待确认的不同指标可覆盖后续已确认版本。增加 latest_report_at，指标相同也推进确认过的最新上传时间；比较指纹包含此时间。同值不改指标或来源批次。
2. XLSX 共享字符串索引损坏导致 IndexError 和 500。解析层转成明确格式错误，422 返回且无事实写入。
3. 广告区间逐对比较有平方复杂度。改为按身份排序扫描，100 组随机区间与朴素结果一致；评审者 10000 行同身份基准从约 7.73 秒降至 0.031 秒。

前两项先增加失败用例再修复，回归通过。没有配置额外整洁清理工具；检查了模块边界、无原始用户文件入仓、依赖锁文件与 diff 空白。

## 红线核对

| 要求 | 证据 |
|---|---|
| 销售跨文件去重与较新状态替换 | comparison.py 的 compare；SalesRecord 唯一约束；test_reports.py 重叠、旧版、同时间冲突、不同账号同店铺用例 |
| 确认原子性与并发 | service.py 的 confirm_import 按用户、店铺加锁，刷新批次并复查比较指纹；PostgreSQL 并发用例 |
| 店铺范围和上传者身份 | routes.py 的 scope、service.py 的 get_batch/confirm_import；跨店铺及授权撤销用例 |
| 广告区间和旧预览 | comparison.py 的 overlapping_keys/compare；旧预览与同值版本回归用例 |
| 输入有界、文件私有 | parsers.py 的 MAX_ROWS/MAX_COLUMNS/excel_rows；service.py 限流读取与 600 文件权限 |
| 无原始买家信息接口 | parsers.py 规范字段白名单；routes.py 仅返回规范 data；原文件无公开下载路由 |
| 金额与汇总 | Decimal 四位金额、SalesRecord/AdRecord 定点字段；routes.py 按币种/状态分组、汇总比率 |
| 数据库往返有界 | comparison.py 按 300 键分批查询；service.py 批量写入；批次列表 defer 大 JSON |
| 切店重建页面与权限导航 | App.tsx 以店铺 key 卸载报表页面；ReportImports.tsx 受 can_confirm 和 reports.import 控制 |

后端路径相对 apps/api/app/reports/，测试路径相对 apps/api/tests/，前端路径相对 apps/web/src/。
