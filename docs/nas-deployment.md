# 绿联 NAS 部署与基础资料迁移

目标设备：DXP4800S，局域网 IP `192.168.31.230`。ERP 已于 2026-10-11 部署，地址为
`http://192.168.31.230:8080`。原管理员账号登录及 API、数据库、Redis 健康检查均已通过。

实机核对：店铺 2、供应商 2、商品 35、供应商报价 33、账号 2、成本/头程费配置 55、
FBA 费率 4；销售、广告、库存、采购、发货、导入记录和历史待办均为 0。
验证记录保存在本机 `.local/nas-deploy/nas-live-verification.json`。

## 迁移范围

保留店铺、供应商、商品、商品店铺关系、供应商报价及商品关联、成本/头程费配置、
FBA 费率及其目录删除标记、现有用户账号和店铺权限。密码哈希原样保留，原密码可继续登录。

不迁移销售、广告、品牌广告分摊、库存余额/流水、供应商备货、采购单、发货单、
仓库、历史待办/通知、导入记录/原始文件、登录会话和审计记录。
商品 `source_data` 中的 `stock` 和 `monthly_sales` 也会移除。
商品图片保留已有外部 URL；此批资料没有需要复制的本地附件。

导出脚本只读取本机数据库，使用一致性快照。导入只接受固定的表白名单，必须在空库中执行，
按外键顺序写入并校验完整内容和运营表零记录；失败整体回滚。
成功后记录包摘要，重复启动跳过导入，避免覆盖日后录入的数据。不同包会被拒绝。

## 生成部署包

在项目根目录执行，输出文件必须尚不存在：

```bash
.venv/bin/python scripts/nas_master_data.py export .local/nas-deploy/master-data.json --env-file .env
.venv/bin/python scripts/package_nas.py --master-data .local/nas-deploy/master-data.json
```

压缩包写入 `.local/nas-deploy/<时间>/sjlerp-nas.zip`，包含应用源码、构建文件、
已解析环境变量的 `docker-compose.yaml` 和 `migration/master-data.json`。
数据库和 Redis 使用独立随机密码，不复制电脑上的 `.env`。
包中含账号密码哈希、供应商资料和 NAS 数据库密码，应存放在受控目录。

## NAS 部署

1. 文件管理 → 共享文件夹 → docker，上传并解压部署包，得到 `sjlerp-nas` 目录。
2. Docker → 项目 → 创建，项目名 `sjlerp-nas`，存放路径选择解压后的 `sjlerp-nas`。
3. 从 NAS 导入该目录的 `docker-compose.yaml`，创建并运行。
4. 首次需要联网拉取 PostgreSQL、Redis、Python、Node、Nginx 官方镜像及锁定的软件依赖。
5. `bootstrap` 先执行 Alembic，再导入基础资料。成功退出（代码 0）是正常状态。
6. `api`、`web`、`worker`、`scheduler`、`postgres`、`redis` 为长期运行服务。
7. 打开 ERP 地址，使用原账号密码登录，核对商品/店铺/供应商数量、成本与报价，
   确认销售/广告/库存/采购/发货为空。

绿联 Docker 可能因一次性 `bootstrap` 已退出而把整个项目标为「异常」。本次已确认它
为 `Exited (0)`，且上述六个长期服务均在运行；应结合退出码和 `/health/ready` 判断。
不要为了让一次性任务保持运行而修改其导入逻辑或重复导入数据。

### NAS 无法连接 Docker Hub 时

本次 NAS 直连 Docker Hub 超时，因此准备了离线方案。将官方的 Linux amd64
`postgres:18.6`、`redis:8.2.9`、`python:3.12-slim`、`nginx:1.28-alpine`
通过 Docker 保存格式的 `.tar` / `.tar.gz` 文件导入 NAS「本地镜像」。
下载时必须选择 Linux amd64，不能导出 Mac 的 ARM 镜像代替；镜像内容应校验 SHA-256。

在可联网电脑构建 Web，并下载 Linux Python 3.12 的 wheel：

```bash
npm --prefix apps/web ci
npm --prefix apps/web run build
.venv/bin/python -m pip download --dest .local/nas-deploy/offline/wheels \
  --only-binary=:all: --platform manylinux2014_x86_64 \
  --platform manylinux_2_28_x86_64 --platform manylinux_2_17_x86_64 \
  --python-version 3.12 --implementation cp --abi cp312 \
  -r apps/api/requirements.lock -r infra/nas/requirements-extra.lock
.venv/bin/python scripts/package_nas.py --master-data .local/nas-deploy/master-data.json --offline
```

离线包包含 `offline/wheels`、`offline/web-dist` 和专用 Dockerfile。
镜像导入后再构建项目，Python 安装使用 `--no-index`，网页直接复制构建产物。
已部署过且已有业务数据时不要重新生成随机数据库密码，应保留当前配置中的密码。
Dockerfile 会设置镜像内应用文件的属主和读取权限，避免 NAS 解压后的权限导致
非管理员应用进程无法加载 `app.main` 或 Nginx 无法读取静态资源。

若使用终端，在解压后的包目录运行：

```bash
docker compose -f docker-compose.yaml up -d --build
docker compose -f docker-compose.yaml ps -a
docker compose -f docker-compose.yaml logs --tail=100 bootstrap api worker scheduler
curl --fail http://192.168.31.230:8080/health/ready
```

不要在本机项目根目录直接用 NAS 配置启动；它绑定的是 NAS 的 IP。
本仓库 `infra/nas/compose.yml` 是环境变量模板，直接使用需先按同目录 `.env.example`
创建 `.env`，并将迁移文件放在根目录 `migration/master-data.json`。

## 持久化、升级与备份

数据库、Redis 和上传文件使用项目专属 Docker 命名卷。正常停止、重启、重建容器保留数据。
不要使用 `down -v` 或删除这些卷作为日常操作。

升级前先停止应用写入，备份数据库与附件卷，并保存部署配置；保存当前镜像用于代码回滚。
数据库已升级后，旧镜像可能不兼容新结构，回滚应同时恢复对应数据库备份。
NAS 上线后以 NAS 为唯一新数据录入入口，电脑实例保留旧运营记录供查询。

数据库备份（在 NAS 部署目录执行，文件不会写入源码仓库）：

```bash
mkdir -p backups
chmod 700 backups
umask 077
docker compose -f docker-compose.yaml exec -T postgres pg_dump -U sjlerp -d sjlerp -Fc > "backups/sjlerp-$(date +%Y%m%d-%H%M%S).dump"
docker compose -f docker-compose.yaml exec -T api tar -C /data/storage -czf - . > "backups/storage-$(date +%Y%m%d-%H%M%S).tar.gz"
```

需要跨数据库与文件的一致性备份时，先停止 `web`、`worker`、`scheduler`，等待正在处理的
API 请求结束后再执行备份，完成后启动。备份应另存一份到另一设备。

当前入口按局域网 HTTP 配置，使用 `SJL_ENVIRONMENT=local` 与非 Secure Cookie。
只发布 NAS 的 8080 入口，数据库、Redis 和 API 无宿主机端口映射。
若以后需要外网访问，另行配置 HTTPS、允许来源和安全 Cookie。
