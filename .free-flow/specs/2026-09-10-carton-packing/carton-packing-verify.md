---
doc_type: verify
slug: carton-packing
status: pass
verified_at: 2026-09-10
---

## 验收契约核对

| 契约 | 验证及结果 |
|---|---|
| 商品箱规、重量维护及非法值 | API回归通过，涵盖零、负数、小数/布尔箱规、超限、重量精度和非有限值；浏览器快捷保存成功 |
| 采购可零散件数、展示箱数重量 | API采购49件成功；浏览器25件/12件每箱显示2箱＋1件、6.2500kg |
| 快捷编辑立即刷新 | 浏览器从采购表单打开商品编辑器，修改SKU、中文名称、箱规10、单重0.5；保留采购25件并即时显示新标签、2箱＋5件、12.5000kg |
| 整箱发货 | API供应商及仓库发货非法整箱均422，库存无多余预留；浏览器49件/10件每箱被表单拦截，改40件保存成功 |
| 快照与本行修改 | API商品箱规12→5不影响旧单，新单采用5；旧单独立改为8成功；浏览器40件货件箱规10→8后显示5箱并记录变更 |
| 状态、范围、历史和分批接收 | API错店铺/错行/权限不足及已发修改拒绝；历史空箱规待发不能发出；仍允许接收1件 |
| 迁移兼容 | SQLite与PostgreSQL隔离schema回退再升级通过，原采购件数、发货件数及状态保留，新增历史箱规保持null |
| 无额外业务行为 | 金额、库存件数/流水、采购分配和实际分批接收规则保留，无自动对外消息；开发验收使用隔离数据库，后续本地部署按用户授权执行 |

## 命令与结果

- `cd apps/api && ../../.venv/bin/python -m pytest -q`：68 passed，7 skipped（PostgreSQL专用测试在SQLite环境跳过），0 failed；随后新增迁移测试，`tests/test_packing.py` 5 passed。
- PostgreSQL隔离schema执行 `tests/test_supply.py tests/test_packing.py`：11 passed（包含库存预留与并发收货）；随后新增迁移回退/升级测试单独运行1 passed。各测试自动清理schema。
- `npm --prefix apps/web run build`：TypeScript与Vite构建成功（修复前后均完成）；保留既有主包体积提示。
- 默认Node不支持项目现有 `--experimental-strip-types` 参数，改用Codex已安装Node运行 `--experimental-strip-types --test apps/web/tests/*.test.mjs`：7 passed，0 failed。
- `git diff --check`：通过。
- 浏览器：本机18081端口、临时SQLite及测试账号完成上述采购/商品/发货交互，并视觉检查发货详情表格布局。
- 独立评审及复审通过，详见同目录review记录。

## 交付结论

pass，可交付。代码与迁移已完成，后续按用户授权于2026-09-10完成本地部署；备份、迁移、四个服务及两个入口检查均通过，详见release部署记录。重量默认采用单件kg；待发状态可修改本单箱规。
