# 本地开发与启动

## 1. 项目运行方式

Web、API 和后台任务使用独立进程。数据库使用 PostgreSQL，队列使用 Redis。所有本地服务仅绑定回环地址。

- Web：`http://127.0.0.1:5173`
- API：`http://127.0.0.1:8000`
- PostgreSQL：`127.0.0.1:15432`
- Redis：`127.0.0.1:16379`

端口固定，遇到占用会报错，不自动改端口。数据库、文件、凭据和日志保存在被 Git 忽略的 `.local/`；编译工具和源码保存在 `.runtime/`。

## 2. 安装应用依赖

使用 Python 3.12 和与前端锁文件兼容的 Node。项目目录执行：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r apps/api/requirements.lock
npm --prefix apps/web ci --registry=https://registry.npmjs.org
.venv/bin/python scripts/dev.py init
```

`init` 仅在 `.env` 不存在时创建配置，生成随机数据库和 Redis 密码。已有配置不会被覆盖。`.env.example` 用于说明配置字段，不包含可直接用于正式环境的密码。

## 3. 选择数据库和队列启动方式

两种方式使用相同本地端口，一次只启动其中一种。

### 已有 Docker

```bash
docker compose --env-file .env -f infra/compose.yml up -d
```

Compose 提供数据库和队列，应用仍通过下述本地命令启动。此配置是本地开发设施配置，不是生产部署方案。

### 没有 Docker，使用项目独立实例

系统已有 `initdb`、`pg_ctl` 和 `redis-server` 时可以直接使用；也可以在具备编译工具的 macOS / Linux 下构建到项目目录：

```bash
bash scripts/build-local-services.sh
.venv/bin/python scripts/dev.py infra-up
```

构建脚本下载指定版本并校验摘要，只写入项目 `.runtime/`，不安装全局服务。编译日志保存在 `.runtime/logs/`。这是本地验证构建，生产运行环境应单独配置 TLS、资源和运维策略。

## 4. 初始化数据库与管理员

```bash
.venv/bin/python scripts/dev.py migrate
.venv/bin/python scripts/dev.py create-admin --generate
```

管理员默认邮箱为 `admin@shujianlu.local`，随机密码保存到 `.local/admin-credentials.txt`，文件仅当前操作系统用户可读。不会创建固定通用密码、默认店铺或虚构经营数据；已有凭据文件不被覆盖。

如需自行指定账号及密码：

```bash
.venv/bin/python scripts/dev.py create-admin --email you@example.com --name 管理员
```

密码通过交互输入，或仅为当前进程设置 `SJL_BOOTSTRAP_PASSWORD`。不要把管理员密码放进源码、提交记录或启动命令参数。

M1 的 `admin` 是公司经营管理员，拥有全部店铺范围；其他角色只拥有明确分配的店铺，空列表表示无店铺。技术管理员与经营管理员分离是后续角色扩展，不应把当前 admin 理解为仅负责系统配置的账号。

## 5. 启动与停止

```bash
.venv/bin/python scripts/dev.py run
```

运行 API、worker 和 Web，日志保存在 `.local/logs/api.log`、`worker.log` 和 `web.log`。按 Ctrl+C 结束应用进程。也支持 `run api`、`run worker`、`run web` 分别运行。

首次登录后先维护店铺和用户。销售、广告和库存还未导入时，工作台显示数据尚未建立，不显示虚构销售或利润。

### 发布到本地预览

先构建网站，停止已运行的开发应用进程，再启动已构建的版本：

```bash
npm --prefix apps/web run build
.venv/bin/python scripts/dev.py infra-up
.venv/bin/python scripts/dev.py migrate
.venv/bin/python scripts/dev.py run --built
```

访问地址仍为 `http://127.0.0.1:5173/`，复用已有账号和业务数据。此模式从 `apps/web/dist/` 提供页面，API 由同源代理连接；修改源码后需重新构建才会更新。仅供本机使用，未设置开机自启；电脑重启后按上述命令重新启动。该本地预览服务不作为公网生产服务器。

本地独立数据库与 Redis 停止命令：

```bash
.venv/bin/python scripts/dev.py infra-down
```

Docker 模式停止命令：

```bash
docker compose --env-file .env -f infra/compose.yml down
```

上述停止命令保留数据。不要使用删除卷的参数来做日常停机。

## 6. 验证与故障定位

在项目根目录执行后端隔离测试（默认 SQLite）：

```bash
(cd apps/api && ../../.venv/bin/python -m pytest -q)
```

使用本地 PostgreSQL、Redis 和真实 worker 完成集成验收：

```bash
.venv/bin/python scripts/verify_m1.py
```

集成脚本要求本地基础服务已启动，以及 `.env` 中的 PostgreSQL 账号可创建测试数据库；它使用一次性数据库和独立测试队列，结束后清理。后端测试也支持通过 `SJL_TEST_DATABASE_URL` 指向独立 PostgreSQL 测试库，每个测试使用独立 schema。

前端验证同样在项目根目录执行：

```bash
npm --prefix apps/web run typecheck
npm --prefix apps/web run build
```

健康接口 `/health/live` 判断进程存活，`/health/ready` 检查数据库和队列可用性。具体本轮验证结果记录在 M1 实施记录中。

如果登录失败，检查账号是否已创建、Web 地址是否在 `SJL_ALLOWED_ORIGINS` 内，以及本地 HTTP 是否配置 `SJL_COOKIE_SECURE=false`。正式 HTTPS 环境必须使用安全 Cookie。

如数据库迁移失败，先查看错误并核对连接配置，不删除数据库来绕过迁移。如果后台任务失败，先查看任务错误与 worker 日志，修正原因后使用授权重试。
