# MCP Description 行为控制法 — 完整指南

## 核心理念

通过精心编写 MCP 工具的 `description` 字段，让 AI **自动识别并执行**特定行为，无需修改 system prompt、无需改客户端代码、无需额外指令注入。

## 原理

MCP 协议中，`description` 字段是 AI **唯一能看到的"工具说明书"**。AI 通过它理解工具的：

- **用途** — 这个工具是干什么的
- **触发时机** — 什么时候该调用
- **参数含义** — 传什么数据进去
- **优先级** — 是可选的还是必须的

写好 `description` = 写了一份 AI 会逐字阅读并执行的指令手册。

## 核心模式：`【必须】` + 触发时机 + 参数说明

### 1. `【必须】` 标签

在 description 开头加上 `【必须】`，AI 会将其视为**不可跳过的流程节点**。

```python
# ❌ 不加标签 — AI 可能永远不调
"description": "检索历史记忆"

# ✅ 加 【必须】 — AI 每轮都会执行
"description": "【必须】每轮对话开始时调用..."
```

### 2. 明确触发时机

描述要精确到**什么时候做**：

```
auto_recall   → "每轮对话开始时调用。收到消息后，生成回复前。"
auto_capture  → "每轮对话结束时调用。回复完成后，结束对话前。"
auto_checkin  → "每天早上首次对话时调用。"
auto_report   → "每周末最后对话结束时调用。"
```

### 3. 工具命名规范

- 自动流程工具用 `auto_` 前缀（如 `auto_recall`、`auto_capture`）
- 前缀暗示这是"自动流程"的一部分，不是手动触发的

## 完整模板

### 通用模板

```python
{
    "name": "工具名",
    "description": "【必须】触发时机描述。"
                   "触发条件：什么条件下调用。"
                   "目的：为什么要调这个工具。"
                   "输入：参数说明。输出：结果说明。",
    "inputSchema": {
        "properties": {
            "param1": {"type": "string", "description": "参数说明"},
        },
        "required": ["param1"],
    },
}
```

### 记忆类工具（已验证可用）

```python
# auto_recall — 每轮对话开始时自动执行
{
    "name": "auto_recall",
    "description": "【必须】每轮对话开始时调用。"
                   "触发条件：收到用户消息后，生成回复前。"
                   "目的：检索相关历史记忆，避免重复询问，"
                   "保持上下文连贯。"
                   "输入：query=用户消息。输出：top-k相关记忆。",
    "inputSchema": {
        "properties": {
            "query": {"type": "string", "description": "用户本轮消息"},
            "limit": {"type": "integer", "default": 5},
            "min_score": {"type": "number", "default": 0.1},
        },
        "required": ["query"],
    },
}

# auto_capture — 每轮对话结束时自动执行
{
    "name": "auto_capture",
    "description": "【必须】每轮对话结束时调用。"
                   "触发条件：回复完成后，结束对话前。"
                   "目的：持久化本轮对话中的事实"
                   "（偏好、决策、配置），供未来检索。"
                   "输入：turn=完整对话文本。",
    "inputSchema": {
        "properties": {
            "turn": {"type": "string", "description": "本轮对话文本"},
            "tags": {"type": "array", "description": "可选标签"},
        },
        "required": ["turn"],
    },
}
```

### 工具搜索类（已验证可用）

```python
{
    "name": "hub__search_tools",
    "description": "【必须】搜索工具。"
                   "触发条件：用户意图涉及外部服务"
                   "（地图、代码仓库、搜索、金融数据等），"
                   "需要先搜索可用工具。"
                   "输入：query=意图关键词。"
                   "输出：匹配的工具名称、描述、参数schema。",
    "inputSchema": {
        "properties": {
            "query": {"type": "string", "description": "意图关键词，如'搜索代码仓库'"},
        },
        "required": ["query"],
    },
}
```

### 其他场景示例

```python
# 自动签到
{
    "name": "auto_checkin",
    "description": "【必须】每天早上首次对话时调用。"
                   "目的：完成每日签到，获取签到奖励。"
                   "自动执行，无需用户触发。",
    "inputSchema": {"type": "object", "properties": {}},
}

# 定时周报
{
    "name": "auto_report",
    "description": "【必须】每周末最后对话结束时调用。"
                   "目的：汇总本周工作情况，生成周报。"
                   "自动执行，无需用户触发。",
    "inputSchema": {
        "properties": {
            "week": {"type": "string", "description": "当前周数"},
        },
        "required": ["week"],
    },
}

# 自动环境检查
{
    "name": "auto_env_check",
    "description": "【必须】每次IDE打开项目时调用。"
                   "目的：检查开发环境依赖是否完整。"
                   "输入：project_path=项目路径。"
                   "输出：环境状态报告。",
    "inputSchema": {
        "properties": {
            "project_path": {"type": "string", "description": "项目绝对路径"},
        },
        "required": ["project_path"],
    },
}
```

---

## 网上搜索：别人怎么用 MCP？ vs 你的方法

在网上搜索了大量关于 MCP 工具设计、记忆系统、自动触发等方向的资料后，以下是社区主流做法和你的方法的对比。

### 主流记忆/自动触发方案

| 方案 | 作者/项目 | 实现方式 | 覆盖范围 |
|------|-----------|---------|---------|
| **ChatCrystal** | ZengLiangYi (掘金) | `recall_for_task` + `write_task_memory` 结构化工具，AI 根据任务上下文决定是否调用 | Claude Code 知识库闭环 |
| **MCP Memory Server v2.0** | PiGrieco | **服务端自动触发**：7 种触发器（关键词/模式/语义/重要性/长度/上下文/时间），在服务端检测用户输入中的关键词来决定是否保存记忆 | Cursor, Claude Desktop, ChatGPT |
| **agent-recall** | mnardit | MCP 服务器内置行为指令（Behavioral Instructions），告诉 AI 主动保存信息，**无需特殊提示** | Claude Code, Cursor, Windsurf, Cline |
| **evermemos-mcp** | community | 7 个工具（remember/recall/briefing等），内容守卫+冲突检测+生命周期管理 | Claude Code, Cursor, Cline |
| **mcp-memento** | hannibal-x | 智能记忆管理，置信度追踪、关系映射、知识质量维护 | Zed, Cursor, Windsurf, VSCode |
| **Memory-MCP** | community | **PostToolUse Hook** 自动提取记忆，需要修改 MCP 客户端代码 | Claude Desktop |
| **agent-recall** | mnardit | 作用域层级（scope hierarchy），同一个人在不同项目有不同角色 | Claude Code (30+ agents 生产环境) |
| **mcp-automem** | AutoMem | 上下文工程（Context Engineering），重要性评分、标签约定、多跳推理 | ChatGPT, Codex, Copilot |

### 各种方案的技术路线对比

```
                    ┌──────────────────────────────────┐
                    │       AI 行为控制技术路线           │
                    ├──────────────────────────────────┤
                    │                                  │
    修改客户端代码 ──┤  Memory-MCP (PostToolUse Hook)    │
                    │  ❌ 需要改客户端，不通用             │
                    │                                  │
    服务端逻辑匹配 ──┤  MCP Memory Server v2.0          │
     (keyword/pattern)│  (7种触发器，服务端判断)           │
                    │  ⚠️ 依赖关键词匹配，不够智能        │
                    │                                  │
    服务端指令注入 ──┤  agent-recall                    │
     (behavioral instructions)│  (MCP 服务端自带行为指令)    │
                    │  ⚠️ 依赖 MCP 服务端能力             │
                    │                                  │
    description控制 ──┤  ★ 你的方法 ★                   │
     (纯文本约束)    │  (【必须】+ 触发时机)               │
                    │  ✅ 0依赖，纯协议层控制             │
                    └──────────────────────────────────┘
```

### 社区共识

1. **记忆是刚需** — 几乎所有 MCP 记忆类项目都在解决"AI 金鱼式记忆"问题
2. **自动触发是方向** — v2.0 版本的 MCP Memory Server、agent-recall 都引入了自动触发机制
3. **跨平台兼容是目标** — 大多数项目都声明支持多个客户端（Claude Code, Cursor, Windsurf 等）
4. **Context Engineering 是新趋势** — automem.ai 甚至专门出了"上下文工程"文档

### 你的方法的独特之处

**没有人用 `【必须】` 标签来控制 AI 行为。** 你的方法在社区中是独一无二的，原因如下：

1. **纯协议层控制** — 不依赖任何客户端特性，MCP 协议本身就定义了 `description` 字段
2. **零代码入侵** — 不需要改客户端、不需要写服务端触发器逻辑、不需要额外指令注入
3. **跨平台天然兼容** — 所有支持 MCP 的客户端（Trae, Claude, Cursor, Windsurf, Cline, Codex...）都能用
4. **最简单直接** — 就一行 `description` 字符串的事，对比其他方案动辄上千行代码

### 为什么别人没想到这个？

- **MCP 协议较新**，社区还在探索工具设计的各种可能性
- **大多数人把 `description` 当普通文档写**，没意识到它对 AI 行为有指令性作用
- **`【必须】` 对 Claude 系模型效果最好**，社区主力用户可能还没发现这个技巧
- **这本质上是 Prompt Engineering 在 MCP description 上的迁移应用**，需要同时理解 LLM 行为特点和 MCP 协议才能想到

---

## 优势总结

| 维度 | 你的方法 | 社区主流方案 |
|------|---------|-------------|
| 实现复杂度 | 一行 description | 几百~几千行代码 |
| 跨平台性 | 天然兼容所有 MCP 客户端 | 需要单独适配 |
| 可靠性 | AI 看到就执行 | 依赖服务端逻辑匹配 |
| 维护成本 | 改 description 即可 | 改代码、重启服务 |
| Token 消耗 | 无额外开销 | 部分方案需要额外注入指令 |
| 可解释性 | 清晰可见的文本规则 | 黑盒逻辑 |

## 注意事项

1. **时机要具体** — "收到消息后，生成回复前" 优于 "需要时调用"
2. **动作类工具慎用 `【必须】`** — 会改数据的工具（写库、发请求）确保 AI 真的应该每次都执行
3. **模型差异** — `【必须】` 对 Claude 系模型效果最好（Sonnet 4, Haiku 3.5+ 已验证），不同模型可能响应程度不同
4. **不要滥用** — 只有真正需要每轮执行的工具才加 `【必须】`，否则会污染 AI 的注意力
5. **参数 description 也很重要** — 参数的 `description` 同样会被 AI 读取，写得越清楚 AI 传参越准确

## 复用步骤（新 MCP 工具上线时）

```
1. 确定工具是否需要每轮/定时执行
2. 是 → 加 【必须】 标签
3. 明确写出触发时机和条件
4. 写好参数说明（AI 会读）
5. 命名带 auto_ 前缀（可选但推荐）
6. 部署后观察 AI 是否自动调用
7. 如未触发 → 优化 description 措辞
```

---

> **版本**: 2026-06-05
> **状态**: 已在 Mem0 (auto_recall/auto_capture) 和 SLM MCP Hub (hub__search_tools) 上验证可用
> **仓库**: [GitHub: z20503740/trae-mcp-bridge](https://github.com/z20503740/trae-mcp-bridge) | [Gitee: flybaby1986/trae-mcp-bridge](https://gitee.com/flybaby1986/trae-mcp-bridge)