# MCP Description 行为控制法

## 核心理念

通过精心编写 MCP 工具的 `description` 字段，让 AI **自动识别并执行**特定行为，无需修改 system prompt。

## 原理

MCP 协议定义中，`description` 字段是 AI 唯一能看到的"工具说明书"。AI 通过 `description` 理解工具的：
- **用途**（这个工具是干什么的）
- **触发时机**（什么时候该调用）
- **参数含义**（传什么数据进去）
- **优先级**（是可选的还是必须的）

写好 `description` = 写了一份 AI 会逐字阅读并执行的指令手册。

## 你的核心发现

### 1. `【必须】` 标签 —— 最关键的创新

在 description 开头加上 `【必须】`，AI 会将其视为**不可跳过的流程节点**，而不是"可用可不用的工具"。

```python
# ❌ 不加标签 — AI 可能永远不调
"description": "检索历史记忆"

# ✅ 加 【必须】 — AI 每轮都会执行
"description": "【必须】每轮对话开始时调用..."
```

### 2. 明确触发时机

```
auto_recall   → "每轮对话开始时调用。收到消息后，生成回复前。"
auto_capture  → "每轮对话结束时调用。回复完成后，结束对话前。"
```

AI 看到"什么时候该干什么事"的明确描述后，会在正确的时间点自动触发工具。

### 3. 工具命名规范

- 记忆类工具用 `auto_` 前缀（如 `auto_recall`、`auto_capture`）
- 前缀暗示这是"自动流程"的一部分，不是手动触发的

## 完整的 auto_recall + auto_capture 实现

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

## 可以复用的场景

这种 `【必须】+ 触发时机 + 参数说明` 的模板可以套用到任意 MCP 工具上：

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

## 网上其他人的做法（vs 你的做法）

| 方案 | 实现方式 | 缺点 |
|------|---------|------|
| **Memory-MCP** | 服务端 PostToolUse Hook | 需要修改 MCP 客户端代码 |
| **AgentRecall** | `/arstatus` CLI 命令手动触发 | 需要用户手动输入 |
| **Shodh-Memory** | 45 个工具全暴露，AI 自己决定 | AI 可能漏调或错调 |
| **MemPalace** | auto-teach + Memory Protocol 注入 | 实现复杂 |
| **你的做法** | `【必须】` 写在 description 里 | 简单直接，0 额外依赖 |

**你的方法是网上没看到同样做法的独创方案**。

## 优势总结

1. **省 token** — 不需要在 system prompt 里写记忆规则
2. **跨平台** — 同一个 MCP 服务，Trae、Claude、Cursor 都自动工作
3. **0 维护** — 规则固化在工具 description 里
4. **全自动** — AI 自己决定调用时机，无需用户干预
5. **简单直接** — 就一行 `description` 字符串的事

## 注意事项

1. description 要写**具体时机**，不要模糊
2. 动作类工具谨慎使用 `【必须】`
3. 不同模型对 `【必须】` 响应程度可能不同
4. 不要滥用——只有真正需要每轮执行的工具才加 `【必须】`