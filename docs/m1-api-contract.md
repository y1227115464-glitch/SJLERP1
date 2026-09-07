# M1 前后端协作约定

M1 实施使用真实 API 和数据库。当前只展示已实现的功能；销售、利润、库存等缺少数据时不制造经营数值。入口 `/api/v1`，本地 Web `http://127.0.0.1:5173`，API `http://127.0.0.1:8000`，Vite 代理 `/api` 和 `/health`。

所有 ID 使用字符串。日期使用 ISO 8601。列表统一 `{items: [], total: number}`。错误为 `{error: {code: string, message: string, details?: unknown}}`。列表支持 `limit`（默认 50，最大 200）和 `offset`。

## 认证

- `POST /auth/login`：JSON `{email, password}` → `{user, csrf_token}`，设置 HttpOnly `sjlerp_session` Cookie。
- `GET /auth/me` → `{user, csrf_token}`；未登录返回 401。
- `POST /auth/logout` → 204。
- 非登录写请求均携带 `X-CSRF-Token`；所有写请求使用 `X-Requested-With: SJLERP`；后端检查允许的 Origin。
- User：`{id, email, display_name, role, is_active, store_ids: string[], permissions: string[]}`。
- Role：`admin | manager | operator | finance | warehouse`。权限由后端返回，UI 不自行推断。

## 店铺和用户

- `GET /stores` → 店铺列表，仅返回有权访问的店铺。
- `GET /stores/{id}` → 店铺详情；不可访问 ID 返回 404。
- `POST /stores` / `PATCH /stores/{id}`：`{name, code, legal_entity, brand, marketplace, currency, is_active?}`。
- Store：`{id, name, code, legal_entity, brand, marketplace, currency, is_active, created_at}`。
- `GET /stores/export` → 权限内 CSV；声明在动态 ID 路由之前。
- `GET /users` → 账号列表（权限 `users.manage`）。
- `POST /users`：`{email, display_name, password, role, store_ids}`。
- `PATCH /users/{id}`：`{display_name?, role?, store_ids?, is_active?, password?}`。
- `GET /roles` → `{items: [{key, label, permissions: string[]}], total}`。
- 不允许停用自身或撤销最后一个有效管理员；变更角色/权限/密码/停用会撤销该账号已有会话。

## 工作台和基础能力

- `GET /workspace` → `{store_count, user_count: number | null, pending_jobs, unread_notifications, recent_activity: Audit[], data_status: {orders: null, advertising: null, inventory: null}, environment}`，全部来自数据库，非管理员 user_count 为 null。
- `GET /audit-logs` → 日志列表：`{id, action, resource_type, resource_id, actor_name, summary, created_at}`；日志不包含密码或会话原文。
- `GET /notifications` → 通知列表：`{id, title, message, is_read, created_at}`；当前用户私有。
- `POST /notifications/{id}/read` → 更新后的通知。
- `GET /jobs` → 当前用户可见任务列表。
- `POST /jobs`：`{kind: "workspace_check", store_id?: string}` → 202 任务；供验证任务执行与通知链路。
- `POST /jobs/{id}/retry` → 202 任务，仅允许有权限的人重试失败任务。
- Job：`{id, kind, status, store_id, created_at, started_at, finished_at, attempts, error_message, result}`，status 为 `queued | running | succeeded | failed`。
- `POST /attachments`：multipart 文件与可选 store_id；`GET /attachments` 列表，`GET /attachments/{id}/download` 受同样范围权限控制。
- Attachment：`{id, filename, content_type, size_bytes, store_id, created_at}`。

`GET /workspace`、`GET /jobs`、`GET /attachments`、`GET /audit-logs` 支持可选 `store_id` 查询参数，由服务端校验该店铺的访问范围并过滤结果；省略时返回当前用户的授权范围。无审计权限的角色不会通过工作台获得最近审计动态。
- `GET /approvals` → 当前用户有权访问的审批数据，M1 先建立数据模型及查询基础。

## 权限键

`workspace.view`、`stores.view`、`stores.manage`、`stores.export`、`users.manage`、`audit.view`、`jobs.view`、`jobs.run`、`files.view`、`files.upload`、`notifications.view`、`approvals.view`、`costs.view`、`finance.view`。

## 运行约定

- 后端从 `apps/api` 运行 `uvicorn app.main:app`，初始化数据库使用 Alembic，管理员初始化使用 `python -m app.cli create-admin`（交互密码或环境变量，不写固定密码）。
- 配置使用 `SJL_` 前缀，例如 `SJL_DATABASE_URL`、`SJL_REDIS_URL`、`SJL_STORAGE_PATH`、`SJL_ALLOWED_ORIGINS`、`SJL_COOKIE_SECURE`、`SJL_ENVIRONMENT`。
- 默认 PostgreSQL URL 由环境变量提供。SQLite 仅用于显式 local 演示或单元验证，不作为 PostgreSQL 验收替代。
- 后台进程 `python -m app.worker`，RQ + Redis；业务任务状态持久化并可恢复调度。
