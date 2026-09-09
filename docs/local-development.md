# 本地开发与启动

## 1. 项目运行方式

Web、API 和后台任务使用独立进程。数据库使用 PostgreSQL，队列使用 Redis。默认仅绑定回环地址；局域网部署可单独开放 Web 入口，见下文。

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

访问地址仍为 `http://127.0.0.1:5173/`，复用已有账号和业务数据。此模式从 `apps/web/dist/` 提供页面，API 由同源代理连接；修改源码后需重新构建才会更新。未设置开机自启；电脑重启后按上述命令重新启动。该本地预览服务不作为公网生产服务器。

### 局域网部署与后台运行

在根目录 `.env` 中配置 Web 监听地址和允许登录的完整来源（将示例 IP 换成服务电脑的实际局域网 IPv4）：

```dotenv
SJL_WEB_HOST=0.0.0.0
SJL_ALLOWED_ORIGINS=http://127.0.0.1:5173,http://localhost:5173,http://192.168.31.23:5173
SJL_COOKIE_SECURE=false
```

使用已经安装好的依赖和项目独立数据库，在根目录执行：

```bash
bash scripts/local.sh start
bash scripts/local.sh status
# 停止应用、项目数据库及队列，保留全部数据：
bash scripts/local.sh stop
```

`start` 会启动数据库和队列、执行迁移，并在后台运行构建后的前端、API、worker 和 scheduler；首次缺少 `dist/` 时自动构建。关闭终端后服务继续运行，电脑重启后重新执行 `start`。日志位于 `.local/logs/`，管理员密码位于 `.local/admin-credentials.txt`。首次部署仍需先执行前述 `create-admin --generate` 创建管理员。

前台运行可使用 `.venv/bin/python scripts/dev.py run --built --host 0.0.0.0`；`--host` 优先于 `.env` 的 `SJL_WEB_HOST`。API、PostgreSQL 和 Redis 继续仅监听 `127.0.0.1`，浏览器通过 Web 的同源代理访问 API。

2026-09-08 本机部署入口为 `http://192.168.31.23:5173/`，使用 Python 3.12.7、Node 22.10.0、PostgreSQL 14.18 和 Redis 8.0.3。已有 Homebrew 程序通过 `.local/bin/` 链接供后台脚本使用，数据独立保存在本项目 `.local/`；未接入系统已有 Redis 的 6379 端口。此工作副本没有随仓库携带旧数据库或导入文件，初始化后业务档案为空。

其他设备连接同一局域网后，用服务电脑的 IP 打开入口。电脑需保持开机且不进入睡眠。IP 变化时更新 `.env` 的 `SJL_ALLOWED_ORIGINS` 并停止、重新启动服务；路由器可为服务电脑保留固定 DHCP 地址。若本机能访问而其他设备不能，检查是否连接访客 Wi-Fi、路由器是否启用设备隔离，以及主机防火墙是否允许 TCP 5173。

修改前端源码后，先 `stop`，执行 `npm --prefix apps/web run build`，再 `start`。此部署使用局域网 HTTP；不要将 5173 端口映射到公网。

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


### 工作台提醒调度

`python scripts/dev.py run all` / `bash scripts/local.sh start` 现同时启动独立 `app.tasks.worker`，每10秒处理待办事件、周期实例和到期通知；单独运行可用 `.venv/bin/python scripts/dev.py run scheduler`。日志为 `.local/logs/scheduler.log`。不要用浏览器定时器或 RQ 长任务替代此进程。部署须先备份数据库，再将 Alembic 升级到 `48b7a65dc109`，随后启动新 API 和 scheduler。

没有新增环境变量，也不覆盖 `.env`。规则初始为空，用户在工作台启用模板后生效。异常事件保留 `attempts/error_message/retry_at`，最长每小时重试；工作台向相关操作者提示单据待办尚未同步。已完成业务不会因为调度异常回滚。
