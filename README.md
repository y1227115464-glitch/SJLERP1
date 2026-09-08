# 书剑录 ERP · SJLERP

SJLERP（书剑录 ERP）是面向美国站亚马逊多店铺业务的内部 Web 管理系统，以 FBA 业务为主，规划统一管理店铺、商品、销售、广告、利润、库存、采购与物流。

已可运行：账号权限、店铺、附件、后台任务、通知和审计，以及商品管理、商品 CSV 导入、供应商档案和采购报价。已将用户提供的 35 个商品、2 家供应商及 33 条报价导入本地真实数据库；阶梯、税费说明和原始来源分别保留。主体档案、店铺 SKU 映射、正式成本和经营报表仍按计划推进。完整业务范围见 [ERP 功能规划](docs/erp-product-plan.md)，任务进度见 [开发执行计划](docs/development-plan.md)，验证结果见 [实施记录](docs/implementation-log.md)。

## 本地运行

完整步骤见 [本地开发与启动](docs/local-development.md)。已准备好本地依赖时，在项目目录运行：

```bash
.venv/bin/python scripts/dev.py infra-up
.venv/bin/python scripts/dev.py migrate
.venv/bin/python scripts/dev.py run
```

Web 地址为 `http://127.0.0.1:5173`。首次安装需按启动文档创建管理员，系统不提供固定通用密码。订单、广告导入及采购财务等业务模块仍在后续里程碑内。

## 已确认建设范围

- 原一期、二期功能均纳入本轮建设：经营分析、利润财务、库存补货、采购、仓库及头程入仓。
- 店铺订单和广告由人员从亚马逊导出文件，再手动导入 ERP；自动接口同步留待后续。
- 库存、交易、结算及费用数据建议同样采用报表导入，内部采购、收发货、物流和付款在 ERP 登记。
- 开发可按依赖分批推进，本轮最终交付包含上述完整业务流程。

## 开发顺序

1. M1：工程基础与账号权限。
2. M2：业务基础档案与期初数据。
3. M3：数据导入中心及报表适配。
4. M4：销售、广告与预估经营分析。
5. M5：采购、审批与仓库作业。
6. M6：头程、FBA 接收与补货。
7. M7：财务对账、实际利润与月结。
8. M8：完整业务验收与交付准备。

现有实现采用 React + TypeScript + Ant Design、FastAPI、PostgreSQL，以及独立 Python 后台任务；依赖版本已通过前后端锁文件固定。

## 文档

- [ERP 功能规划与本轮验收范围](docs/erp-product-plan.md)
- [开发执行计划、任务清单与资料准备](docs/development-plan.md)
- [Web ERP 技术方案](docs/erp-technical-plan.md)
- [本地开发与启动](docs/local-development.md)
- [实施记录与验证结果](docs/implementation-log.md)
- [商品、供应商与采购报价使用说明](docs/catalog-management.md)
- [早期本地利润分析工具技术方案（历史参考）](docs/technical-plan.md)
