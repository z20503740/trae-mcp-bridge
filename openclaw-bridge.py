#!/usr/bin/env python3
"""
OpenClaw MCP Bridge — 让 Trae 通过 MCP 协议调用 201 的 OpenClaw

功能：
  1. Agent 对话     → 向 OpenClaw main agent 发送消息
  2. Shell 执行     → 在 201 执行命令
  3. 配置管理       → 读写 OpenClaw 配置文件
  4. 信息查询       → Skills/Agents/Gateway 状态

架构：
  Trae (stdio MCP) → 本脚本 (stdin/stdout JSON-RPC) → SSH → 201 的 openclaw CLI
"""

import json
import subprocess
import sys
import os
import tempfile

SSH_HOST = "192.168.0.201"
SSH_USER = "z20503740"
OPENCLAW_CONFIG_PATH = "/home/z20503740/.openclaw/openclaw.json"
OPENCLAW_WORKSPACE = "/home/z20503740/.openclaw/workspace"
GATEWAY_TOKEN = "82030a5c0222984ac856c3c2fa3e478b812bde4579fa00b3"


def ssh_run(cmd: str, timeout: int = 60) -> str:
    """Run a command on 201 via SSH and return stdout."""
    full_cmd = ["ssh", f"{SSH_USER}@{SSH_HOST}", cmd]
    result = subprocess.run(
        full_cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        error = result.stderr.strip() or result.stdout.strip()
        raise RuntimeError(f"SSH command failed (exit {result.returncode}): {error}")
    return result.stdout.strip()


def ssh_run_json(cmd: str, timeout: int = 60) -> dict:
    """Run a command and parse JSON output."""
    out = ssh_run(cmd, timeout)
    return json.loads(out)


# ----- MCP Tool Handlers -----

HANDLERS = {}


def tool(name: str, description: str, input_schema: dict):
    """Decorator to register an MCP tool handler."""
    def decorator(fn):
        HANDLERS[name] = {
            "fn": fn,
            "description": description,
            "inputSchema": input_schema,
        }
        return fn
    return decorator


@tool(
    "openclaw_agent_turn",
    "【必须】调用 OpenClaw 201 的 main agent 执行任务。"
    "触发条件：用户需要与 OpenClaw 交互、或需要在 201 上执行 AI 任务、"
    "或需要让 OpenClaw 自我优化配置时调用。"
    "目的：让 OpenClaw 在 201 服务器上执行 AI 任务并返回结果。"
    "输入：message=发送给agent的消息。输出：agent的回复内容。",
    {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "发送给 OpenClaw agent 的消息内容",
            },
            "agent_id": {
                "type": "string",
                "description": "目标 agent ID（默认 main）",
                "default": "main",
            },
        },
        "required": ["message"],
    },
)
def handle_agent_turn(message: str, agent_id: str = "main") -> str:
    """Send a message to OpenClaw's agent and get response."""
    # Use openclaw agent command via SSH with correct CLI syntax
    escaped_msg = message.replace("'", "'\\''")
    cmd = f"openclaw agent --agent {agent_id} -m '{escaped_msg}' 2>&1"
    return ssh_run(cmd, timeout=120)


@tool(
    "openclaw_exec",
    "【必须】在 OpenClaw 201 服务器上执行 Shell 命令。"
    "触发条件：需要在 201 上运行命令（检查状态、修改配置、操作文件等）时调用。"
    "目的：远程操作 201 服务器。"
    "输入：command=要执行的shell命令。输出：命令执行结果。",
    {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "要在 201 上执行的 shell 命令",
            },
            "timeout": {
                "type": "integer",
                "description": "超时时间（秒），默认 60",
                "default": 60,
            },
        },
        "required": ["command"],
    },
)
def handle_exec(command: str, timeout: int = 60) -> str:
    """Execute a shell command on 201."""
    return ssh_run(command, timeout=timeout)


@tool(
    "openclaw_config_get",
    "读取 OpenClaw 201 的完整配置文件内容。"
    "触发条件：需要查看 OpenClaw 配置时调用。"
    "目的：了解当前 OpenClaw 的配置状态。"
    "输入：无。输出：当前 openclaw.json 内容。",
    {
        "type": "object",
        "properties": {},
    },
)
def handle_config_get() -> str:
    """Read OpenClaw config file."""
    return ssh_run(f"cat {OPENCLAW_CONFIG_PATH}")


@tool(
    "openclaw_config_update",
    "更新 OpenClaw 201 的配置文件。"
    "触发条件：需要修改 OpenClaw 配置（添加 Agent、修改模型、启用 Skill 等）时调用。"
    "目的：修改 OpenClaw 配置后重启 Gateway 生效。"
    "输入：config_json=完整的 openclaw.json 内容。"
    "输出：配置更新结果。",
    {
        "type": "object",
        "properties": {
            "config_json": {
                "type": "string",
                "description": "完整的 openclaw.json 内容（JSON 字符串）",
            },
        },
        "required": ["config_json"],
    },
)
def handle_config_update(config_json: str) -> str:
    """Update OpenClaw config file."""
    # Validate JSON
    try:
        parsed = json.loads(config_json)
    except json.JSONDecodeError as e:
        return f"Error: Invalid JSON - {e}"

    # Write via SSH using a temp file approach
    tmp_file = f"/tmp/openclaw-config-{os.getpid()}.json"
    try:
        # Write config content to temp file on 201
        encoded = json.dumps(parsed)
        ssh_run(f"cat > {tmp_file} << 'EOF'\n{encoded}\nEOF")
        # Back up current config
        ssh_run(f"cp {OPENCLAW_CONFIG_PATH} {OPENCLAW_CONFIG_PATH}.bridge-bak")
        # Replace config
        ssh_run(f"mv {tmp_file} {OPENCLAW_CONFIG_PATH}")
        return f"Config updated. Backup saved to {OPENCLAW_CONFIG_PATH}.bridge-bak"
    except Exception as e:
        return f"Error updating config: {e}"


@tool(
    "openclaw_gateway_restart",
    "重启 OpenClaw 201 的 Gateway 服务。"
    "触发条件：修改配置后需要重启 Gateway 使其生效时调用。"
    "目的：使配置更改生效。"
    "输入：无。输出：重启结果。",
    {
        "type": "object",
        "properties": {},
    },
)
def handle_gateway_restart() -> str:
    """Restart the OpenClaw gateway service."""
    return ssh_run("openclaw gateway restart 2>&1", timeout=30)


@tool(
    "openclaw_skills_list",
    "列出 OpenClaw 201 上所有可用的 Skills。"
    "触发条件：需要了解当前有哪些 Skill 可用时调用。"
    "目的：查看 Skill 状态（ready/disabled）。"
    "输入：无。输出：Skills 列表。",
    {
        "type": "object",
        "properties": {},
    },
)
def handle_skills_list() -> str:
    """List all OpenClaw skills."""
    return ssh_run("openclaw skills list 2>&1", timeout=30)


@tool(
    "openclaw_agents_list",
    "列出 OpenClaw 201 上所有配置的 Agents。"
    "触发条件：需要查看当前 Agent 列表时调用。"
    "目的：了解当前有哪些 Agent 及其配置。"
    "输入：无。输出：Agents 列表。",
    {
        "type": "object",
        "properties": {},
    },
)
def handle_agents_list() -> str:
    """List all OpenClaw agents."""
    return ssh_run("openclaw agents list 2>&1", timeout=30)


@tool(
    "openclaw_gateway_status",
    "检查 OpenClaw 201 的 Gateway 运行状态。"
    "触发条件：需要确认 Gateway 是否正常运行时调用。"
    "目的：健康检查。"
    "输入：无。输出：Gateway 状态信息。",
    {
        "type": "object",
        "properties": {},
    },
)
def handle_gateway_status() -> str:
    """Check OpenClaw gateway status."""
    return ssh_run("openclaw gateway status 2>&1", timeout=30)


# ----- MCP Protocol Loop -----

def handle_request(request: dict) -> dict:
    """Process a single JSON-RPC request."""
    req_id = request.get("id")
    method = request.get("method", "")
    params = request.get("params", {})

    if method == "tools/list":
        tools = []
        for name, info in HANDLERS.items():
            tools.append({
                "name": name,
                "description": info["description"],
                "inputSchema": info["inputSchema"],
            })
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools}}

    elif method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        if tool_name not in HANDLERS:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Tool not found: {tool_name}"},
            }

        try:
            handler = HANDLERS[tool_name]
            result = handler["fn"](**arguments)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": str(result)}]
                },
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32000, "message": str(e)},
            }

    elif method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "openclaw-bridge", "version": "1.0.0"},
            },
        }

    elif method == "notifications/initialized":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    else:
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}


def main():
    """Main MCP stdio protocol loop."""
    # Signal readiness
    sys.stderr.write("OpenClaw MCP Bridge started\n")
    sys.stderr.flush()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            response = handle_request(request)
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
        except json.JSONDecodeError as e:
            sys.stderr.write(f"JSON parse error: {e}\n")
            sys.stderr.flush()
        except Exception as e:
            sys.stderr.write(f"Error: {e}\n")
            sys.stderr.flush()


if __name__ == "__main__":
    main()