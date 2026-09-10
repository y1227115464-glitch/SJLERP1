---
doc_type: verify
slug: purchase-followup
status: pass
verified_at: 2026-09-10
---

## 结论
代码可交付；尚未迁移业务数据库或发布。默认合并范围为同店铺、同来源、同目的仓，已在实现前向用户说明。其他合并范围不在本次已实现契约内。

## 自动验证
- `cd apps/api && ../../.venv/bin/python -m pytest -q`：87 passed, 10 skipped，32.17s。跳过项为需PostgreSQL或其他专门环境的测试。
- PostgreSQL 隔离schema：test_purchase_followup、test_supply、test_packing、test_supply_amendments 共26 passed，26.02s；每项迁移独立schema并清理。覆盖重复合并、合并与发货竞争、库存分配及接收并发、迁移兼容性。
- `npm --prefix apps/web run build`：TypeScript + Vite通过。沿用原有大chunk警告。
- 使用 bundled Node 运行 `--experimental-strip-types --test apps/web/tests/*.test.mjs`：7 passed。系统Node版本较旧，不支持该选项，未升级用户环境。
- `git diff --check`：通过。

## 浏览器验收
独立临时SQLite测试服务、Chrome无头独立会话，所有操作仅使用自动构造测试数据。

| 契约 | 结果 |
| --- | --- |
| 未选店铺供应商不能选商品 | 商品控件禁用，通过 |
| 店铺/供应商交集 | 已绑定商品候选total=1，无报价供应商候选total=0，通过 |
| 切换供应商 | 已选商品清空，通过 |
| 售卖店铺维护 | 商品详情售卖店铺页切换开关，PUT成功，通过 |
| 跨页合并 | 第1页与第2页各选1张，选中数保持2，确认后打开目标货件详情，通过 |
| 付款跟进 | 弹窗设已付清并填备注，保存成功，刷新后保留状态及历史，通过 |

## 反向与错误验证
接口测试覆盖缺关系/停用关系、跨店权限、重复候选去重、非法枚举、已收齐采购跟进、重复请求不重复记历史、路线/采购来源/箱规/物流资料冲突、非初始状态、过期版本、重复ID、失败后数量不变。草稿确认绕过问题有先失败再通过回归测试。

独立review两项问题均已修复并复查通过。上线步骤见purchase-followup-release.md；不自动绑全店铺、不实际付款开票、不改历史单价。
