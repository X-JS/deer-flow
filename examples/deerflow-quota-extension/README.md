# DeerFlow 配额扩展（deerflow-quota-extension）

一个独立、可发布的 DeerFlow **Python 扩展**示例：限制**每次运行的工具调用次数**。
它只依赖公开契约包 `deerflow-extension-api`（以及 FastAPI / LangChain），
**不 import `deerflow.*` 或 `app.*`**，因此可以脱离 DeerFlow 源码独立开发与测试。

## 它贡献了什么

| 贡献点 | 行为 |
| --- | --- |
| Middleware | 按 task 统计工具调用；某次运行超过 `tool_calls_per_run` 后，后续工具调用直接返回拒绝信息，**不会执行真正的工具** |
| Task lifecycle | 每个 task 结束时把用量并入进程级聚合 |
| Service | Gateway 运行期间绑定 `ExtensionRuntimeDeps` |
| Router | `GET /api/quota/stats` 返回配置的上限与聚合用量 |

配额计数存放在 **task 级** `ExtensionData` 中，因此每个 lead run 与每个子代理各有独立预算。
Middleware 只通过 `task_store_from_runtime()` 读取该存储，没有 task store 时原样放行。

## 目录结构

```text
deerflow-quota-extension/
├── pyproject.toml                    # 包定义 + deerflow.extensions 入口点
├── README.md
├── deerflow_quota_extension/
│   ├── __init__.py                   # install(registry, config) 入口点
│   └── plugin.py                     # 各贡献点实现
└── tests/
    ├── test_plugin.py                # 契约级单元测试
    └── test_entry_point.py           # 入口点发现测试
```

## 配置项

在 `config.yaml` 的 `plugins:` 记录里通过 `config` 传入：

| 键 | 默认 | 说明 |
| --- | --- | --- |
| `enabled` | `true` | 为 `false` 时 `install()` 不注册任何东西 |
| `tool_calls_per_run` | `50` | 每次运行允许的工具调用次数上限 |

```yaml
plugins:
  - name: quota
    package: deerflow-quota-extension
    use: deerflow_quota_extension:install
    enabled: true
    required: false
    config:
      tool_calls_per_run: 50
```

---

## 一、本地开发与测试（独立项目）

契约包 `deerflow-extension-api` 目前**没有发布到包索引**，因此本仓库根目录下自带一份。
注意：**不要**在本包的 `pyproject.toml` 里加 `[tool.uv.sources]` 指到本地路径——
那样虽然能让本目录 `uv sync` 成功，但会让 `deerflow extensions install` 失败：管理器会把本包
**快照**复制到 `backend/extensions/sources/`，相对路径随即失效。

正确做法是显式安装契约包 + 本包（可编辑）：

```bash
cd examples/deerflow-quota-extension
uv venv --python 3.12
uv pip install -e ../../backend/packages/extension-api
uv pip install -e ".[dev]"
uv run --no-project pytest -q
uv run --no-project ruff check .
uv run --no-project ruff format --check .
```

测试只使用公开契约与本包声明的依赖，不导入 DeerFlow harness 或 Gateway 应用。

---

## 二、开发一个扩展的整体流程

```text
① 新建独立包（pyproject + 实现 + 测试）
      │  暴露唯一入口点： [project.entry-points."deerflow.extensions"]
      │                    quota = "deerflow_quota_extension:install"
      ▼
② 本地跑通测试（uv venv / uv pip install -e / pytest）
      ▼
③ 用扩展管理器安装到某个 DeerFlow checkout
      │  make extension-install SOURCE=<绝对路径|包名|HTTPS git>
      │  管理器会：校验源码 → 快照到 backend/extensions/sources/<dist>/
      │             → 写 backend/[dependency-groups].extensions + uv.lock
      │             → uv sync → 写/采纳 config.yaml 的 plugins: 记录
      ▼
④ 重启 Gateway（plugins 仅启动时加载）
      ▼
⑤ 运行验证（日志 "Extensions loaded: n/m"、扩展路由、功能行为）
```

### 1. 新建独立包

- 自己的 `pyproject.toml`；依赖 `deerflow-extension-api`，以及你用到的框架（FastAPI/LangChain…）。
- 实现 `install(registry, config)`，用 `@extension(api="0.2.0", name="quota")` 打戳。
- 通过 `registry` 注册贡献点（middleware / task_lifecycle / system_model_observer /
  service / routers / agent_assembly_observer / context_compaction_observer）。
- 写测试；**不要**加 `[tool.uv.sources]`（原因见上）。

### 2. 本地跑通测试

见上一节命令。

### 3. 安装到 Gateway

从 DeerFlow 仓库根执行（本地目录必须用**绝对路径**，因为 `make` 包装器从 `backend/` 运行）：

```bash
make extension-install SOURCE="$PWD/examples/deerflow-quota-extension"
make extension-list
```

等价的手工 CLI（从 `backend/` 执行）——`--yes` 表示已审阅并信任该来源（扩展代码与构建钩子
以 Gateway 权限运行），`--required` 会把加载失败升级为启动中止：

```bash
uv run --frozen --no-group extensions deerflow extensions install <source> [--yes] [--required]
```

管理器会：

1. 先校验目标 `config.yaml` 可写（`uv add/sync` 会执行包的 build backend）；
2. 把本地目录**快照**（拷贝，非 editable 链接）到 `backend/extensions/sources/<distribution>/`；
3. 把该包写入 `backend/pyproject.toml` 的 `[dependency-groups].extensions` 并更新 `backend/uv.lock`；
4. `uv sync --locked --all-packages` 安装到环境；
5. 写入/采纳 `config.yaml` 的 `plugins:` 记录（`name` / `package` / `use` / `enabled` / `required` / `config`）。

任一步失败都会回滚依赖文件、配置、快照与环境；全过程持跨进程锁
`.deer-flow/extension-manager.lock`。

### 4. 重启 Gateway 生效

`plugins:` 是**启动时字段**，只在 Gateway 构造应用时导入一次：

```bash
make dev                          # 本地
docker restart deer-flow-gateway  # 已运行的容器（容器会在启动时按新 lock 同步）
make up                           # 生产 Docker：改了已安装集合后需重建镜像
```

### 5. 验证

```bash
# 启动日志应出现（n/m = 成功数/配置数）
#   Extensions loaded: 1/1 (deerflow_quota_extension:install)
#   Extension routers mounted: deerflow_quota_extension:install -> /api/quota/stats

# 扩展路由已挂载（贡献路由一律要求会话认证，401 表示路由存在但未登录）
curl -s http://localhost:2026/api/quota/stats
```

---

## 三、更新已安装的扩展

当前的扩展管理器**没有就地升级**。改完扩展源码后，按“先移除、再安装、再恢复私有配置”更新：

```bash
# 1) 移除旧版本（会 uv remove、删 plugins 记录、删快照）
make extension-remove NAME=quota

# 2) 安装新版本（同一本地路径；或新的包名 / git 引用）
make extension-install SOURCE="$PWD/examples/deerflow-quota-extension"

# 3) 重启 Gateway
docker restart deer-flow-gateway
```

> 快照是**拷贝**而非可编辑链接，所以直接改 `backend/extensions/sources/...` 不会被运行中的
> 环境采用，必须重新安装并同步。日常迭代请在示例目录用它自己的 venv 跑测试。

只调整运行参数（例如 `tool_calls_per_run`）时，不必重装包——直接改 `config.yaml` 里该记录的
`config` 值，然后重启 Gateway 即可。

## 四、卸载

```bash
make extension-remove NAME=quota      # 或：deerflow extensions remove quota
docker restart deer-flow-gateway
```

`enable` / `disable` 只切换 host 侧的 `enabled` 开关并保留私有配置：

```bash
make extension-disable NAME=quota
make extension-enable  NAME=quota
```

---

## 五、注意事项

- **契约版本兼容**：host 会读取入口点上的 `__deerflow_api__` 并与宿主 `API_VERSION` 比对
  （0.x 要求同 major.minor，且 host ≥ declared）。本包声明 `api="0.2.0"`。
- **fail-open by default**：`required: false` 时，加载失败只记 diagnostic，不影响 Gateway 启动；
  需要“无此扩展即视为部署错误”时才用 `--required`。
- **信任边界**：插件从 `config.yaml` 的 `plugins:` 加载（操作员控制），**不要**放进能被
  Gateway API 改写的 `extensions_config.json`。扩展代码与构建钩子以 Gateway 权限执行，只应安装可信来源。
- **远程来源**：支持 PyPI 包名与**公网 HTTPS Git**；拒绝 SSH Git、`file://` 与本地 wheel。
- **生产镜像**：本地快照会被 `.dockerignore` 重新包含进 backend 构建上下文；改动已安装集合后
  需 `make up` 重建生产镜像（生产容器启动不会联网解析扩展）。

## 六、工作原理（加载期）

Gateway 启动时，`deerflow.extensions.loader.load_extensions()` 按 `config.yaml` 中 `plugins:`
的**列表顺序**逐个处理：解析入口点 → 校验 `__deerflow_api__` → 在归属上下文中调用
`install(registry, config)`（失败则按位置回滚）。随后 `create_app()` 会把中间件注入 agent 构建链、
在 host 路由之后挂载贡献路由、按注册顺序启动 service；task lifecycle / system-model observer /
context-compaction observer 挂到对应的运行点。全过程只发生一次，改配置或启停都必须重启。
