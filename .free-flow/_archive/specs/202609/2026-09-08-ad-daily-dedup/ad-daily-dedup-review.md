# 独立评审及红线

2026-09-08，独立只读评审者 report_review 复核通过，没有剩余阻断问题。

修复一项迁移问题：同批次上传时间相同的旧日报重复项，原先以随机 ID 排序，可能保留文件中的前一行。改为 latest_report_at DESC、source_row DESC、id DESC，评审者使用反向 UUID 复现后确认保留源行 3（花费 9），与新版文件内最后一行一致。迁移回归使用同一上传时间验证该行为。

评审核实：日报键仅日期与 SKU/活动/广告组并隔离店铺，其他属性可覆盖；旧预览不能覆盖更新版本；旧解析批次须重传；日报与历史区间分开汇总；旧批次源行保留。未配置额外整洁清理工具。

| 红线 | 证据 |
|---|---|
| 业务键与唯一约束 | app/reports/parsers.py:114；models.py 的 uq_ad_daily_identity |
| 按店铺串行确认，不取缓存金额 | app/reports/service.py 的 confirm_import；test_ad_daily.py 双账号并发用例 |
| 查询有索引、列表分页 | models.py ix_ad_store_report_date；routes.py 日报/历史条件及 paginated |
| 迁移批量处理，无逐行数据库往返 | 2c638fa481b9 的 rekey：ID 游标每次 300 条、executemany 更新；窗口函数批量识别重复 |
| 不吞异常，源文件与批次留存 | parsers.py、service.py；迁移只合并重复事实，不删除报告批次 |
| 前端请求和分页 | ReportRecords.tsx 同一粒度筛选传给列表/摘要；ReportImports.tsx 分页来源预览，新增日期/广告组列 |

后端文件路径相对 apps/api/，前端相对 apps/web/src/。
