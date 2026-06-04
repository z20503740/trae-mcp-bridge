# Trae IDE MCP Bridge

Trae IDE MCP 桥接中间件 —— 通过 stdio bridge 连接远程 MCP 服务。

## 简介

Trae IDE 原生只支持 stdio 协议的 MCP（启动子进程，通过 stdin/stdout 通信）。
如果你的 MCP 服务跑在远程服务器（HTTP 协议），就需要这两个 bridge 脚本做协议转换。

## 架构

```
┌─ 你的电脑 (Trae IDE) ──────────────────────┐
│                                              │
│  mcp.json ──→ python3 mcp-stdio-bridge.py    │
│               (stdio ↔ HTTP 转换)             │
│                                              │
│  mcp.json ──→ python3 mem0-bridge.py         │
│               (stdio ↔ HTTP 转换)             │
└──────────────────────────────────────────────┘
        │                              │
        ▼                              ▼
┌─ 远程服务器 ───────────────────────┐
│  slm-mcp-hub (端口 52414)          │
│  mem0-server  (端口 8765)          │
└────────────────────────────────────┘
```

## 文件说明

| 文件 | 说明 |
|------|------|
| `mcp-stdio-bridge.py` | SLM MCP Hub 桥接脚本（转发到远程 52414 端口） |
| `mem0-bridge.py` | Mem0 记忆系统桥接脚本（转发到远程 8765 端口） |
| `mcp.json` | Trae IDE 的 MCP 配置模板 |

## 使用方法

### 前提条件

- 你的电脑上安装了 **Python 3**
- 远程服务器上已部署好 slm-mcp-hub 和/或 mem0-server
- 你的电脑能访问远程服务器的对应端口（同局域网或 VPN）

### 第一步：修改 bridge 脚本中的目标地址

将两个 bridge 脚本中的 IP 地址改成你的实际服务器地址：

- `mcp-stdio-bridge.py` 中修改 `HUB_URL` 变量
- `mem0-bridge.py` 中修改 `MEM0_URL` 变量

例如：
```python
# 远程服务器
HUB_URL = "http://192.168.1.100:52414/mcp"

# 本地运行
HUB_URL = "http://127.0.0.1:52414/mcp"
```

### 第二步：配置 Trae IDE 的 MCP

将 `mcp.json` 的内容复制到 Trae IDE 的 MCP 配置文件中：

**Linux**: `~/.config/Trae CN/User/mcp.json`
**macOS**: `~/Library/Application Support/Trae CN/User/mcp.json`
**Windows**: `%APPDATA%\Trae CN\User\mcp.json`

> 注意：`mcp.json` 中的 `args` 路径需要改成你电脑上脚本的实际存放路径。

### 第三步：重启 Trae IDE

打开 Trae IDE 的设置 → MCP，应该能看到两个 MCP 服务已连接。

## 常见问题

**Q: 连接失败？**
A: 检查服务器地址和端口是否可达：`telnet <服务器IP> 52414`

**Q: MCP 工具显示为空？**
A: 检查 slm-mcp-hub 是否正常运行：`curl http://<服务器IP>:52414/mcp`

**Q: 如何自建服务端？**
A: 需要安装 slm-mcp-hub 和 mem0-open-mcp Python 包。

## 许可证

MIT