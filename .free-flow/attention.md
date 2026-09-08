# SJLERP 项目约定

mode: repository

现有产品、技术和交付记录位于 `docs/`，沿用这些文档；本次新增功能的规格与进度放在 `.free-flow/specs/`。

- Python 3.12 / FastAPI / SQLAlchemy 2 / PostgreSQL；SQLite 仅供隔离测试。新业务放 `app/supply/`，复用账号、角色、店铺范围、CSRF 与审计。
- React 19 / TypeScript / Ant Design 6；沿用已有视觉样式，按页面懒加载。表格分页，选择器搜索，切店不显示旧店数据。
- 商品、供应商和仓库为公司共享档案；业务单据与库存必须有店铺归属。没有授权店铺的普通用户不能查看业务记录。
- 金额使用 Decimal；数量为整数。库存变化必须有不可编辑流水、事务、重复提交保护和并发校验。
- 不覆盖 `.env` 或已有 `.local` 数据，不提交凭据；部署前备份数据库，复用局域网入口。
- 验证：`cd apps/api && ../../.venv/bin/python -m pytest -q`；`npm --prefix apps/web run build`；在 PostgreSQL 隔离 schema 验证库存并发。
- 实现结束由独立评审者按 free-review 只读检查，再执行交付验收。未配置额外整洁清理工具。

FastAPI 路由参数由框架注入，不为满足参数数量阈值引入无必要包装；库存批量数据在事务内锁定是正确性要求。
