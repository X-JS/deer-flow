# USE.md — 本地开发与运行指南

本文档面向**Windows 本机 + Git Bash/PowerShell** 的 DeerFlow 本地开发，覆盖：

- Docker 开发环境的完整启动 / 更新 / 停止流程
- 非 Docker（本地进程）开发流程
- 模型 Provider 配置（含 OpenCode Go）
- 验证清单与常见故障排查

> 约定：本文命令默认在**仓库根** `E:\opensource\deer-flow` 执行。Windows 上服务脚本依赖 Git for Windows（`cygpath` 等），**部分流程必须在 Git Bash 中运行**，不能用原生 `cmd.exe`/PowerShell 直接跑 bash 脚本；WSL 也不保证可用。

---

## 0. 服务拓扑

| 服务 | 端口 | 作用 |
| --- | --- | --- |
| **Nginx** | `2026` | 统一入口，浏览器打开这个 |
| **Gateway API** | `8001` | FastAPI + 内嵌 LangGraph 运行时 |
| **Frontend** | `3000` | Next.js Web UI |
| **Provisioner** | `8002` | 仅当沙箱为 provisioner/K8s 模式才需要（本地沙箱模式**不要**启动） |

- 统一入口：<http://localhost:2026>
- API：`http://localhost:2026/api/*`
- LangGraph 兼容 API：`http://localhost:2026/api/langgraph/*`

---

## 1. 前置条件

- Node.js 22+、pnpm（仓库固定 pnpm 10.x，可用 corepack）
- Python + `uv`
- Docker Desktop（仅 Docker 流程需要）
- `make`（仅 `make` 流程需要；Git Bash 默认不自带，可 `scoop install make` / `choco install make`）

检查：

```bash
make check      # 检查 Node/pnpm/uv/nginx 等
make doctor     # 检查配置与系统要求，给出修复建议
```

---

## 2. 配置准备（Docker 和本地开发都需要）

在仓库根需要三个文件（后两者可能已存在，`make config` 可从模板生成）：

| 文件 | 来源 | 说明 |
| --- | --- | --- |
| `config.yaml` | `config.example.yaml` | 主配置（**gitignored**，可在运行时被 Gateway 改写） |
| `extensions_config.json` | `extensions_config.example.json` | MCP servers + skills（**gitignored**） |
| `.env` | `.env.example` | API Key 等环境变量（**gitignored**） |

```bash
# 方式一：交互式向导（推荐新用户）
make setup

# 方式二：从模板复制后手工编辑
make config
```

> `config.yaml` 缺失时服务无法启动。运行时会读取 `.env`（容器通过 `env_file` 注入）。

---

## 3. Docker 开发环境（推荐）

### 3.1 关键约定（很重要）

本机环境下务必遵守：

1. **项目名固定 `-p deer-flow`**：镜像名为 `deer-flow-gateway` / `deer-flow-frontend`。官方 `make docker-start` 用 `-p deer-flow-dev`，镜像名不同，会触发构建。
   > 若你从旧项目名（如 `-p docker`，镜像 `docker-gateway` / `docker-frontend`）迁移过来，先重打标签即可复用、无需重建：
   > ```powershell
   > docker tag docker-gateway:latest  deer-flow-gateway:latest
   > docker tag docker-frontend:latest deer-flow-frontend:latest
   > docker compose -p docker -f docker/docker-compose-dev.yaml down   # 删掉旧项目的容器
   > ```
2. **加 `--no-build`**：复用已构建镜像，避免触发镜像构建。
3. **只启 4 个服务**：`redis frontend gateway nginx`（本地沙箱模式**不启** `provisioner`）。
4. **工作目录为仓库根**，并设置 `DEER_FLOW_ROOT`。

### 3.2 启动

```powershell
cd E:\opensource\deer-flow
$env:DEER_FLOW_ROOT=(Get-Location).Path; docker compose -p deer-flow -f docker/docker-compose-dev.yaml up -d --no-build redis frontend gateway nginx
```

前台运行（实时日志，Ctrl+C 停止）：

```powershell
docker compose -p deer-flow -f docker/docker-compose-dev.yaml up --no-build redis frontend gateway nginx
```

启动后打开 <http://localhost:2026>，首次引导到 `/setup` 创建管理员账号。

### 3.3 状态与日志

```powershell
# 状态
docker compose -p deer-flow -f docker/docker-compose-dev.yaml ps
docker ps --format '{{.Names}} | {{.Status}}'

# 日志（按服务）
docker compose -p deer-flow -f docker/docker-compose-dev.yaml logs -f gateway
docker compose -p deer-flow -f docker/docker-compose-dev.yaml logs -f frontend
docker compose -p deer-flow -f docker/docker-compose-dev.yaml logs -f nginx redis

# 宿主机落盘的日志
Get-Content logs\gateway.log -Tail 50 -Wait
Get-Content logs\frontend.log -Tail 50 -Wait
```

> 注意：`frontend` 容器把输出重定向到 `/app/logs/frontend.log`（挂载到宿主机 `logs/frontend.log`），因此 `docker logs deer-flow-frontend` 通常为空。

### 3.4 更新代码后：升级 / 重启容器（核心操作）

改完代码，先判断“**要不要重建镜像**”，再决定用轻量 `restart`、`--force-recreate`（重建容器）还是 `--build`（重建镜像）。dev compose 里 `backend/` 与 `frontend/src` 是**挂载**的（见 3.1），所以大多数改动不需要动镜像。

| 改动类型 | 重建镜像? | 处理方式 |
| --- | --- | --- |
| `config.yaml`（模型/工具） | 否 | `docker restart deer-flow-gateway`（dev 网关还监听 `*.yaml`，也会自动重载） |
| `.env`（新增/改变量） | 否，但**需重建容器** | `--force-recreate --no-build gateway`（`env_file` 只在容器创建时注入） |
| `backend/` 运行时代码 | 否 | 一般无需操作（uvicorn `--reload` 热重载）；不稳时 `docker restart deer-flow-gateway` 兜底 |
| `frontend/src` | 否 | HMR 自动生效，刷新浏览器即可 |
| 依赖（`pyproject.toml`/`uv.lock`/`package.json`）或 Dockerfile | **是** | `up -d --build <服务>`（见 3.6） |
| 改 compose 文件 / 挂载卷 | 否 | `--force-recreate --no-build <服务>` |

最常用的三条（按“改动从小到大”）：

```powershell
cd E:\opensource\deer-flow

# ① 只改后端代码 / config.yaml → 重启网关（最轻量）
docker restart deer-flow-gateway

# ② 改了 .env 或挂载 → 重建 gateway + nginx（复用镜像，不 build）
$env:DEER_FLOW_ROOT=(Get-Location).Path
docker compose -p deer-flow -f docker/docker-compose-dev.yaml up -d --force-recreate --no-build gateway nginx

# ③ 改了依赖或 Dockerfile → 重新构建镜像
$env:DEER_FLOW_ROOT=(Get-Location).Path
docker compose -p deer-flow -f docker/docker-compose-dev.yaml up -d --build gateway frontend
```

> 重建 `gateway` 时建议**把 nginx 一起重建**：nginx 启动时解析 `gateway` 的 IP，只重建 gateway 会让 nginx 缓存旧 IP 导致 502。
>
> 只改 `config.yaml` / `skills/`（已挂载）或前端源码，**不需要**任何重建镜像的操作。

#### 能只“重启全部容器”吗？

`docker restart` 只重启**现有**容器（环境变量、镜像都不变）。得益于 dev compose 的挂载和启动脚本，它能覆盖多数日常改动，但**不是全部**：

| 改动类型 | 只 `docker restart` 够吗 | 原因 |
| --- | --- | --- |
| `backend/` 代码 | ✅ | 已挂载 + uvicorn `--reload`，其实不重启也生效 |
| `frontend/src` | ✅ | 已挂载 + HMR，不重启也生效 |
| `config.yaml` | ✅ | 已挂载，且 `--reload-include='*.yaml'` |
| `uv.lock` / 后端依赖 | ✅（多数） | 重启时 `dev-entrypoint.sh` 会重跑 `uv sync --locked` |
| `.env` 新增 / 改值 | ❌ | `env_file` 只在**创建容器**时注入，restart 沿用旧环境 |
| 新增 `UV_EXTRAS` | ❌ | 同上，需重建容器 |
| 只改 `pyproject.toml` 未更新 lock | ⚠️ | `uv sync --locked` 会直接失败；先在宿主机 `make install` 刷 lock |
| `frontend/package.json` 依赖 | ❌ | 该文件未挂载，`node_modules` 在镜像里，需 `--build` |
| Dockerfile / 基础镜像 | ❌ | 必须 `--build` |

重启全部容器：

```powershell
cd E:\opensource\deer-flow
$env:DEER_FLOW_ROOT=(Get-Location).Path
docker compose -p deer-flow -f docker/docker-compose-dev.yaml restart
```

> 结论：**日常改后端 / 前端 / 配置，重启（甚至不重启）就够；一旦动了 `.env`、前端依赖或 Dockerfile，就得 `--force-recreate` 或 `--build`。**

### 3.5 停止 / 清理

```powershell
# 停止但保留容器
docker compose -p deer-flow -f docker/docker-compose-dev.yaml stop

# 停止并删除容器/网络（保留数据卷）
docker compose -p deer-flow -f docker/docker-compose-dev.yaml down

# 连数据卷一起删（会丢 Redis 数据、gateway-venv 卷）
docker compose -p deer-flow -f docker/docker-compose-dev.yaml down -v
```

### 3.6 全量重建镜像（谨慎）

```powershell
$env:DEER_FLOW_ROOT=(Get-Location).Path
docker compose -p deer-flow -f docker/docker-compose-dev.yaml down --remove-orphans
docker compose -p deer-flow -f docker/docker-compose-dev.yaml up -d --build redis frontend gateway nginx
```

> ⚠️ **前提**：Docker Desktop 的镜像加速器可用。若 `--build` 报基础镜像
> `node:22-alpine` / `python:3.12-slim-bookworm` / `docker:cli` “not found”，
> 说明加速器（如 `swr.cn-north-4.myhuaweicloud.com`）失效：
> Docker Desktop → Settings → Docker Engine，移除 `registry-mirrors` 中的失效地址后 Apply & Restart。

### 3.7 官方 wrapper（等价命令）

```powershell
& "D:\Program Files\Git\bin\bash.exe" -lc "cd /e/opensource/deer-flow && ./scripts/docker.sh start"
```

`scripts/docker.sh start` 会：读 `config.yaml` 判断沙箱模式自动决定是否启 `provisioner`、创建缺失的 `.env`、`export DEER_FLOW_ROOT`，然后 `up --build -d`。
它用 `-p deer-flow-dev` 且强制 `--build`，在加速器失效时会失败；此时用 3.2 的命令。

### 3.8 生产镜像模式（`make up` / `make down`）

如果你用的是**生产 compose**（`docker/docker-compose.yaml`，镜像不带 dev 挂载，代码是**打进镜像**的），更新代码后**必须重新构建镜像**——`make up` 的默认行为就是 build + start：

```bash
# 在 Git Bash 中执行
make up            # = scripts/deploy.sh：docker compose up --build -d --wait（构建 + 启动 + 等就绪）
make down          # 停止并删除容器
make docker-logs   # 跟踪日志
```

只构建镜像、不启动：

```bash
./scripts/deploy.sh build     # 只 build 全部镜像
./scripts/deploy.sh start     # 用已构建镜像启动（不 build）
```

| 模式 | compose 文件 | 代码位置 | 更新代码后 |
| --- | --- | --- | --- |
| **开发**（3.2–3.6） | `docker-compose-dev.yaml` | `backend/`、`frontend/src` 挂载热重载 | `restart` / `--force-recreate`，多数不用 build |
| **生产**（本节） | `docker-compose.yaml` | 打进镜像 | 必须 `make up`（或 `./scripts/deploy.sh build`）重建 |

> 生产模式的挂载只有 `skills/` 和 `config.yaml` 等运行时文件；`backend/`/`frontend/` 源码改动不会生效，**必须重建**。

---

## 4. 非 Docker 本地开发（Git Bash）

**必须在 Git Bash 中执行**：

```bash
cd /e/opensource/deer-flow
make config     # 首次：生成 config.yaml / extensions_config.json
make install    # 安装前后端依赖 + pre-commit hooks
make dev        # 启动 Gateway + Frontend + Nginx（带热重载）
```

停止：

```bash
make stop       # 或 ./scripts/serve.sh --stop
```

生产模式（本地、已优化）：

```bash
make start      # SKIP_FRONTEND_BUILD=1 可复用上次前端构建
```

---

## 5. 模型 Provider 配置

### 5.1 常规方式

```bash
make setup      # 向导：选择 LLM provider、搜索 provider、沙箱/权限
```

生成的 `config.yaml` 形如：

```yaml
models:
- name: deepseek-v4-1-flash                 # 由 model id 派生（点→横线），探针要用这个 name
  display_name: OpenCode Go (Zen) / deepseek-v4.1-flash
  use: deerflow.models.opencode_provider:OpenCodeChatModel
  model: deepseek-v4.1-flash               # 发给 API 的裸 id
  api_key: $OPENCODE_API_KEY
  base_url: https://opencode.ai/zen/go/v1
  request_timeout: 600.0
  max_retries: 2
  max_tokens: 8192
  supports_vision: false
  default_headers:
    User-Agent: deer-flow/1.0
    x-opencode-session: deer-flow          # 非线程调用的兜底值
  supports_thinking: true
  when_thinking_enabled:
    extra_body:
      thinking:
        type: enabled
  when_thinking_disabled:
    extra_body:
      thinking:
        type: disabled
```

### 5.2 OpenCode Go（Zen）注意事项

- **模型名用裸 id**（`deepseek-v4-flash`）。`opencode-go/<id>` 只是 opencode 自身配置格式，
  发到原始 API 会被拒绝：`401 ModelError: Model ... is not supported`。
- 端点要求 `x-opencode-session`（否则 `400 MissingSessionID`）与可识别的 `User-Agent`。
  用 `deerflow.models.opencode_provider:OpenCodeChatModel` 时，每次请求会带
  `deer-flow:<thread_id>`，**同一会话稳定**（利于路由/prompt 缓存）；无线程上下文的调用
  （标题生成、记忆抽取、独立探针）回退到 `default_headers.x-opencode-session`。
- DeerFlow 不在 OpenCode Go 的“已验证客户端”名单中，Go 会做流量滥用监控；如遇限流/异常，
  建议改用正式 provider。
- `/messages` 家族的模型（`minimax-*`、`qwen3.*`）需另配 `langchain_anthropic:ChatAnthropic`。
- 向导内置 profile 名为 **OpenCode Go (Zen)**，环境变量为 `OPENCODE_API_KEY`。

---

## 6. 验证清单

### 6.1 HTTP 可达

```powershell
# 前端
try { (Invoke-WebRequest http://localhost:2026/ -UseBasicParsing -TimeoutSec 60).StatusCode } catch { $_.Exception.Message }   # 200
# 网关（401 = 可达，需认证）
try { (Invoke-WebRequest http://localhost:2026/api/health -UseBasicParsing -TimeoutSec 15).StatusCode } catch { $_.Exception.Response.StatusCode.value__ }  # 401
```

### 6.2 Gateway 启动完成

```powershell
Get-Content logs\gateway.log -Tail 5     # 期望：Application startup complete.
```

### 6.3 容器内模型端到端探针

先用配置里的 `models[0].name` 替换下文的 `<model-name>`：

```powershell
docker exec deer-flow-gateway sh -lc "grep -m1 '^- name:' /app/project/config.yaml"
```

```powershell
$probe = @'
from deerflow.models.factory import create_chat_model
m = create_chat_model(name="<model-name>")
print("MODEL OK:", m.invoke("reply with the single word ok").content)
'@
$probe | docker exec -i deer-flow-gateway /app/backend/.venv/bin/python -
# 期望：MODEL OK: ok
```

> 名字必须与 `config.yaml` 中该模型的 `name` 字段一致（不是 `model` 字段）。
> 若 `create_chat_model` 报 `ModuleNotFoundError`，用容器内解释器
> `/app/backend/.venv/bin/python`，不要用系统 `python`。

### 6.4 单元测试

```powershell
# 向导 provider 测试（宿主机）
cd backend; uv run pytest tests/test_setup_wizard.py -q

# 前端类型检查（容器内，宿主机可能没装 node_modules）
docker exec deer-flow-frontend sh -lc "cd /app/frontend && pnpm typecheck"
```

---

## 7. 常见故障排查

### 7.1 `provisioner` 容器崩溃（Kubeconfig path is a directory）

本地沙箱模式（`sandbox.use: deerflow.sandbox.local:LocalSandboxProvider`）**不需要** provisioner。
如果裸跑 `docker compose up`（未指定服务列表）会连带启动 `provisioner`，它会把宿主
`~/.kube/config` 挂进容器；若该路径是目录（或不存在被 Docker 建成目录），就会报错循环重启。

**解决**：只启动 `redis frontend gateway nginx`（见 3.2）。

### 7.2 镜像拉取失败（not found）

见 3.6 的加速器说明。临时绕过可从显式源预拉并重打标签：

```powershell
docker pull docker.m.daocloud.io/library/node:22-alpine
docker tag  docker.m.daocloud.io/library/node:22-alpine node:22-alpine
docker pull docker.m.daocloud.io/library/python:3.12-slim-bookworm
docker tag  docker.m.daocloud.io/library/python:3.12-slim-bookworm python:3.12-slim-bookworm
docker pull docker.m.daocloud.io/library/docker:cli
docker tag  docker.m.daocloud.io/library/docker:cli docker:cli
```

### 7.3 前端控制台 hydration mismatch

形如：

```
A tree hydrated but some attributes of the server rendered HTML didn't match the client properties.
- className="__cici_translate_hide_origin_content_wrapper__"
```

这类 `__cici_translate_*` 前缀来自**浏览器扩展**（翻译/AI 助手）在 React 加载前改写 DOM，
不是应用 bug。处理：

1. 对 `localhost:2026` 关闭该类扩展，或用无痕/禁用扩展的窗口验证；
2. 仓库已在 `<html>` 与 `<body>` 上加 `suppressHydrationWarning`（`frontend/src/app/layout.tsx`）
   作为官方兜底压制。

### 7.4 模型报 401 / 400

- `401 ModelError: Model ... is not supported` → 模型名带了聚合器前缀，改用裸 id。
- `400 MissingSessionID` → 缺少 `x-opencode-session` 头（见 5.2）。

### 7.5 前端 `pnpm typecheck` 在宿主机报 `baseUrl has been removed`

宿主机没有 `node_modules`，误用了全局新版 tsc。请在容器内执行（见 6.4）。

### 7.6 查看 `x-opencode-session` 实际发送值（DEBUG 日志）

导出消息 JSON 里的 `thread_id` 是 DeerFlow 内部线程 ID，**不是** `x-opencode-session`
请求头——该头只发给 LLM 端点，不会出现在导出 JSON 里。要确认真实运行时发出的值，
用 `OpenCodeChatModel` 的 DEBUG 日志：

```
deerflow.models.opencode_provider - DEBUG - OpenCode Go x-opencode-session=deer-flow:<thread_id> (thread-scoped)
deerflow.models.opencode_provider - DEBUG - OpenCode Go x-opencode-session=deer-flow (fallback, no thread context)
```

`log_level` 是**启动时字段**（`config.yaml`），默认 `info` 不打印 DEBUG。临时开启：

```powershell
# 1) 把 config.yaml 的 log_level 改成 debug
# 2) 重启网关
docker restart deer-flow-gateway
# 3) 在 UI 发一条消息，触发一次 LLM 调用
# 4) 过滤日志
Select-String -Path logs\gateway.log -Pattern 'opencode_provider'
```

看完把 `log_level` 改回 `info` 并再次重启（debug 会让 sqlalchemy/httpx/uvicorn
等日志显著变多）。该日志是 DEBUG 门控的，保留无副作用。

---

## 8. 命令速查

```powershell
# ── 启动（Docker，复用镜像）──
cd E:\opensource\deer-flow
$env:DEER_FLOW_ROOT=(Get-Location).Path; docker compose -p deer-flow -f docker/docker-compose-dev.yaml up -d --no-build redis frontend gateway nginx

# ── 状态 / 日志 ──
docker ps --format '{{.Names}} | {{.Status}}'
docker compose -p deer-flow -f docker/docker-compose-dev.yaml logs -f gateway
Get-Content logs\frontend.log -Tail 50 -Wait

# ── 更新（改代码后升级重启）──
docker compose -p deer-flow -f docker/docker-compose-dev.yaml restart   # 重启全部（日常改动够用）
docker restart deer-flow-gateway                     # 只改后端/配置：最轻量
docker compose -p deer-flow -f docker/docker-compose-dev.yaml up -d --force-recreate --no-build gateway nginx   # 改了 .env/挂载
docker compose -p deer-flow -f docker/docker-compose-dev.yaml up -d --build gateway frontend                    # 改了依赖/Dockerfile

# ── 生产镜像模式（Git Bash，代码打进镜像，必须重建）──
make up        # build + start
make down

# ── 停止 / 清理 ──
docker compose -p deer-flow -f docker/docker-compose-dev.yaml down
docker compose -p deer-flow -f docker/docker-compose-dev.yaml down -v

# ── 本地进程开发（Git Bash）──
cd /e/opensource/deer-flow && make setup && make install && make dev
```

---

## 9. 参考

- `README.md` — 项目总览与安装
- `CONTRIBUTING.md` — Docker 开发指南
- `config.example.yaml` — 完整配置参考（含各 provider 示例）
- `backend/AGENTS.md`、`frontend/AGENTS.md`、`scripts/AGENTS.md` — 各模块开发约定
