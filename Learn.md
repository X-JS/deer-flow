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
