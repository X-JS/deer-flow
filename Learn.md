# DeerFlow 学习路径

## 第一层：全局认知（1-2 天）

**必读文件**（按顺序）：

1. `README.md` — 项目定位与核心特性概览
2. `docs/ARCHITECTURE.md` — 架构图 + 服务拓扑 + 层级划分
3. 根 `AGENTS.md` — 仓库地图 + 命令速查

**理解目标**：

- 知道四个服务（Nginx 2026 / Gateway 8001 / Frontend 3000 / Provisioner 8002）的角色
- 明确 **Harness / App 分层**：`deerflow.*` 是可发布的 agent 框架，`app.*` 是 FastAPI 应用层，单向依赖
- 知道 `extensions_config.json` 是运行时可编辑的配置中枢

---

## 第二层：一条完整请求的生命周期（3-5 天）

从入口到出口走通一个 run：

```
前端发消息
  → Gateway POST /api/threads/{id}/runs/stream
  → RunManager.try_start() + RunRecord 创建
  → worker.py::run_agent()   （核心执行循环）
  → LeadAgentAssembly（中间件链 + LangGraph graph）
  → StreamBridge 推送到前端 SSE
```

**关键文件**：

- `backend/app/gateway/routers/threads.py` — 路由入口
- `backend/packages/harness/deerflow/runtime/runs/worker.py:868` — `run_agent()` 主循环
- `backend/packages/harness/deerflow/agents/lead_agent/agent.py` — `LeadAgentAssembly`、中间件组装
- `backend/packages/harness/deerflow/runtime/stream_bridge.py` — SSE 推送机制

**附带理解**：`docs/STREAMING.md` 和 `backend/packages/harness/deerflow/agents/middlewares/AGENTS.md`

---

## 第三层：核心子系统（各 1-2 天）

按优先级排序：

| 子系统 | 入口文件 | 文档 |
|--------|----------|------|
| **MCP 集成** | `deerflow/mcp/tools.py`、`mcp/client.py`、`mcp/cache.py` | `deerflow/mcp/AGENTS.md` |
| **Subagent** | `deerflow/subagents/executor.py`、`registry.py` | `deerflow/subagents/AGENTS.md` |
| **Sandbox** | `deerflow/sandbox/sandbox.py`、`local/local_sandbox_provider.py` | `deerflow/sandbox/AGENTS.md` |
| **Memory** | `deerflow/agents/memory/` | `deerflow/agents/memory/AGENTS.md` |
| **Skills** | `deerflow/skills/` | `deerflow/skills/AGENTS.md` |
| **配置系统** | `deerflow/config/` | `deerflow/config/AGENTS.md` |
| **Tracing** | `deerflow/tracing/factory.py` | `deerflow/tracing/AGENTS.md` |

---

## 第四层：Gateway API 层

`backend/app/gateway/AGENTS.md` 是整份最详细的路由文档，逐一过每个 router：

- `routers/mcp.py` — MCP 配置 CRUD
- `routers/threads.py` — 线程/运行管理
- `routers/skills.py` — 技能管理
- `routers/personal_mcp.py` — 用户级 MCP

---

## 第五层：前端

`frontend/AGENTS.md` 有完整说明，重点路径：

- `src/core/threads/` — 线程状态与流式处理
- `src/core/api/stream-mode.ts` — LangGraph stream 模式
- `src/core/mcp/` — MCP 前端状态管理
- `tests/unit/` 和 `tests/e2e/` — 测试规范

---

## 辅助手段

- **单测驱动理解**：每个子系统目录旁都有对应测试，写不了代码就先读测试看它验证什么
- **`make support-bundle`** — 排障时自动收集，了解输出结构能反推系统内部状态
- **`make doctor`** — 检查当前环境是否完整，帮助定位配置问题

---

## 建议切入点

先从**第二层（请求生命周期）**入手，因为它会把其他所有子系统串起来；孤立学某个子系统容易不知其用。

---

# 学习任务书

> 全栈背景 · 二次开发目标 · 高强度节奏（每天 2h+）
> 完成一项任务后，在对应行末尾填写完成日期，例如：`- [x] 1.1 ... 2026-09-30`

---

## 阶段一：打通主链路（Day 1-3）

**目标**：跑通一次完整 run，理解"一句话消息 → agent 思考 → SSE 推回前端"的全路径。

### 任务 1.1 — 抓一次真实 SSE 事件流
- [ ] 启动 `make dev`，在浏览器发一条消息
- [ ] 打开 DevTools → Network → 找到 SSE 连接，记录事件类型
- [ ] **产出**：截图，标注 `values` / `messages-tuple` / `custom` / `end` 各出现的位置和次数
- **关键文件**：`backend/app/gateway/routers/threads.py`

### 任务 1.2 — 精读 run_agent() 主循环
- [ ] 通读 `worker.py` 中 `run_agent()` 函数（约 1126 行起）
- [ ] 画出 5 个阶段的时序图：admission → preflight → graph astream → postflight → finalize
- [ ] **产出**：保存为 `docs/learn/run_agent-flow.md`（可用 Mermaid 格式）
- **关键文件**：`runtime/runs/worker.py`

### 任务 1.3 — 追踪 middleware 链组装顺序
- [ ] 在 `agent.py::_assemble_lead_agent()` 中标注每个 middleware 的插入位置
- [ ] 列出：middleware 名称、作用、在模型调用前/后的位置
- [ ] **产出**：一张 middleware 顺序表
- **关键文件**：`agents/lead_agent/agent.py`、`agents/middlewares/AGENTS.md`

### 任务 1.4 — 用 DeerFlowClient 走通一次程序化对话
- [ ] 写一个最小脚本调用 `DeerFlowClient.stream()`，订阅 `values` 和 `messages-tuple`
- [ ] 记录每个事件类型的内容结构
- [ ] **产出**：可运行的脚本 + 输出日志
- **关键文件**：`deerflow/client.py`

---

## 阶段二：理解核心子系统（Day 4-8）

**目标**：能独立读懂每个子系统的关键路径。

### 任务 2.1 — MCP Session Pool 生命周期
- [ ] 精读 `mcp/AGENTS.md`，画出 session pool 状态机：idle → initializing → ready → evicted
- [ ] **产出**：session pool 状态机图（保存为 `docs/learn/mcp-session-pool.md`）
- **关键文件**：`mcp/cache.py`、`mcp/client.py`

### 任务 2.2 — 添加一个真实 MCP Server 并观察工具生效
- [ ] 通过 `POST /api/mcp/config/servers` 添加一个 stdio MCP server（如 `npx -y @modelcontextprotocol/server-filesystem`）
- [ ] 在对话中触发该 server 提供的工具，确认 agent 能看到
- [ ] **产出**：操作步骤 + 工具出现在 agent 工具列表的截图
- **关键文件**：`routers/mcp.py`

### 任务 2.3 — Subagent 双 ID 设计
- [ ] 读 `subagents/executor.py`，理解 `execution_id`（进程级）和 `tool_call_id`（provider 级）为何要分开
- [ ] **产出**：一段文字解释两者分离原因（200 字以内）
- **关键文件**：`subagents/executor.py`、`subagents/AGENTS.md`

### 任务 2.4 — Skill 注入 Prompt 机制
- [ ] 找 `skills/public/deep-research/SKILL.md`，读其结构
- [ ] 追踪 skill 内容何时、如何被合并进 agent system prompt
- [ ] **产出**：说明 skill 注入的时机和位置（哪个 middleware、哪行代码）
- **关键文件**：`skills/public/*/SKILL.md`、`deerflow/skills/`、`agents/lead_agent/prompt.py`

### 任务 2.5 — Sandbox Acquire/Release 生命周期
- [ ] 读 `sandbox/AGENTS.md`，理解 local sandbox 与远程 sandbox 的 acquire/release 差异
- [ ] **产出**：sandbox 生命周期时序图
- **关键文件**：`sandbox/local/local_sandbox_provider.py`、`sandbox/AGENTS.md`

### 任务 2.6 — DeerMem 触发与持久化
- [ ] 读 `agents/memory/AGENTS.md`，理解何时触发 fact 提取、结果存在哪里
- [ ] **产出**：说明 extract → queue → persist 的触发时机和数据流向
- **关键文件**：`agents/memory/`

---

## 阶段三：动手写 Extension（Day 9-14）

**目标**：独立完成一个最小可用的 Python extension。

### 任务 3.1 — 通读 Extension API 契约
- [ ] 精读 `extension-api/contracts.py`，列出 `ExtensionRegistry` 所有 hook
- [ ] **产出**：手写一份 hook 速查表（hook 名、触发时机、入参类型）
- **关键文件**：`packages/extension-api/deerflow_extension_api/contracts.py`

### 任务 3.2 — 写第一个 Extension：自定义 Tool
- [ ] 仿照 `examples/deerflow-extension-example/`，写一个 extension：注册一个 tool，返回当前时间戳
- [ ] 确保可编译、可安装
- [ ] **产出**：完整 extension 包（含 `pyproject.toml`）
- **关键文件**：`examples/deerflow-extension-example/`

### 任务 3.3 — 安装并验证 Tool 生效
- [ ] 运行 `make extension-install SOURCE=./your-extension`
- [ ] 在对话中触发该 tool，确认 agent 可以调用并看到返回值
- [ ] **产出**：运行截图 + agent 调用 tool 的日志
- **关键文件**：项目根 `Makefile`

### 任务 3.4 — 扩展：增加 Middleware Hook（打印 token 用量）
- [ ] 在 extension 中实现 `MiddlewareContributor`，在每次模型调用后打印 token 用量
- [ ] **产出**：日志截图，显示每次模型调用的 token 数据
- **关键文件**：`extensions/registry.py`、`extension-api/contracts.py`

### 任务 3.5 — 扩展：增加自定义 Router 端点
- [ ] 在 extension 中注册一个 `GET /api/my-ext/status` 端点，返回 extension 状态信息
- [ ] **产出**：curl 或浏览器访问截图
- **关键文件**：`extensions/registry.py::routers()`

---

## 阶段四：深入专项（Day 15+，三选一）

从以下三个方向任选一个深入，形成自己的知识体系。

### 方向 A — 流式机制
- [ ] 读 `runtime/stream_bridge.py` + `docs/STREAMING.md`
- [ ] 读前端 `src/core/api/stream-mode.ts`，理解各 stream mode 的差异
- [ ] **最终产出**：一份流式事件类型说明文档（含事件触发时机、消费方）

### 方向 B — 中间件链
- [ ] 读 `agents/middlewares/AGENTS.md`，逐个 middleware 读源码
- [ ] 读各 middleware 对应测试，理解边界条件
- [ ] **最终产出**：一份 middleware 调试笔记（每个 middleware 做什么、何时介入、异常时行为）

### 方向 C — MCP 安全边界
- [ ] 精读 `routers/mcp.py::_validate_mcp_update_request`
- [ ] 读 `mcp/AGENTS.md` 中 "Stdio launch policy at the HTTP boundary" 段落
- [ ] **最终产出**：一份安全边界总结（API 层禁止什么、允许什么、为何这样设计）

---

## 每日进度登记

在下方追加每日完成记录：

```
## Day N 完成
- [x] 1.2 worker.py run_agent 阶段分析 ✓ (日期: YYYY-MM-DD)
- [ ] 1.3 middleware 链追踪（进行中）
```
