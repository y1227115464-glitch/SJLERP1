---
doc_type: verify
slug: default-fba
status: pass
verified_at: 2026-09-10
---

# 验证记录

- 先行测试：3 条测试分别因发货缺少目的仓、调整缺少仓库、新建仓默认 domestic 失败，确认测试覆盖新行为。
- 后端 SQLite 全量：74 passed、8 skipped；跳过项需要 PostgreSQL。
- PostgreSQL 独立临时数据库：test_default_fba、test_supply、test_packing 共 18 passed，包含并发首次建仓、库存占用与接收竞争；临时数据库已清理，未改业务库。
- 前端构建：npm --prefix apps/web run build 通过。保留已有大包体积提示。
- 前端现有测试：使用 Codex 自带 Node 执行 --experimental-strip-types --test tests/*.test.mjs，7 passed。系统 Node 不支持该参数，未修改项目或系统运行时。
- git diff --check 通过。

覆盖：缺省 FBA、空系统建仓、重复提交、停用仓跳过、失败事务回滚、同仓转运拒绝、类型筛选对应余额/流水/摘要/在途、店铺隔离、旧显式仓库兼容。

前端通过类型检查、构建和独立代码评审；未在浏览器执行人工点击验收。代码已完成，本次未重启或部署运行中的应用。
