# 书剑录 ERP API · M1

Python 3.12、FastAPI、SQLAlchemy、Alembic、PostgreSQL、Redis/RQ。准确依赖版本见 `requirements.lock`，直接依赖约束见 `requirements.in`。

从本目录运行（根脚本会加载根 `.env`）：

```sh
../../.venv/bin/python -m alembic upgrade head
../../.venv/bin/python -m app.cli create-admin --email your-email@example.com --name 管理员
../../.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
../../.venv/bin/python -m app.worker
```

管理员密码交互输入，至少 12 个字符；自动化可从 `SJL_BOOTSTRAP_PASSWORD` 环境变量读取。工具拒绝覆盖已有邮箱账号。数据库迁移不创建默认用户、固定密码、经营店铺或模拟经营数值。

## 配置

配置以 `SJL_` 为前缀：`DATABASE_URL`、`REDIS_URL`、`STORAGE_PATH`、`ALLOWED_ORIGINS`（逗号分隔）、`COOKIE_SECURE`、`ENVIRONMENT`、`SESSION_HOURS`、`MAX_UPLOAD_BYTES`、`QUEUE_NAME`、`JOB_TIMEOUT_SECONDS`。Cookie 默认开启 Secure，本地 HTTP 必须显式设为 `false`。生产环境强制 Secure。

PostgreSQL 为主数据库。只有显式 `SJL_ENVIRONMENT=local` 或 `test` 时才能指定 SQLite URL。SQLite 验证不能替代 PostgreSQL 验证。

`/health/live` 表示进程存活；`/health` 和 `/health/ready` 检查数据库连接与 Redis，成功返回 200，任何依赖故障返回 503。不会向响应暴露连接字符串。开发 API 文档为 `/api/docs`。

## 权限和基础能力

- 服务端会话 Cookie：HttpOnly、SameSite=Lax、固定有效期，数据库仅保存会话标识摘要。写入要求已允许的 Origin、`X-Requested-With: SJLERP` 和会话 CSRF Token（登录不要求 CSRF）。
- 账号停用、密码、角色或店铺授权变更会撤销既有会话。不能停用自己或撤销最后一个有效管理员。失败登录按邮箱和客户端地址持久限流。
- 管理员访问全部店铺；其他角色只访问显式分配店铺，空授权无店铺访问权。后台任务执行前重新核对发起人授权。历史任务结果的店铺范围超出当前权限时不返回该结果。
- 经理、财务可读权限内审计；运营、仓库不读取审计日志，包括工作台最近动态。密码摘要、会话原文、文件存储路径不进入 API 对象或日志。
- 附件以随机文件键存储在私有目录，仅通过鉴权下载接口访问。文件名清理、流量/文件大小限制、空文件拒绝、下载强制二进制附件。支持按店铺和本人私有资料授权。
- `workspace_check` 是实际读取数据库的基础检查任务。持久化状态、尝试次数、结果和通知；Redis 故障时保留 queued 意图。worker 每 5 秒恢复队列调度，超时 running 标记 failed，可由发起人或管理员重试。重复执行不重复产生结果和通知。
- macOS 使用 RQ SpawnWorker，Linux 使用 Worker。独立 worker 必须持续运行；当前还没有导入解析器。审批提供持久化模型和权限查询，审批流和业务单据在后续里程碑实现。

## 验证

```sh
../../.venv/bin/python -m pytest -q
```

默认测试使用隔离 SQLite 临时数据库，每个测试通过 Alembic 创建结构。PostgreSQL 测试设置 `SJL_TEST_DATABASE_URL` 到独立测试数据库；每个测试使用独立 schema 并在结束后移除。测试不会使用主业务数据库。真实 RQ/Redis/worker 集成由仓库运行脚本验证。

测试覆盖登录、来源校验、CSRF、过期、停用和授权变更、最后管理员、限流、敏感值不回显、跨店读取/导出/筛选、附件、权限撤销、幂等任务执行、失败重试、超时恢复、调度竞态和历史汇总权限缩减。
