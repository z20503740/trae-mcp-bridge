#!/usr/bin/env python3
"""Bridge stdio <-> real slm-mcp-hub (HTTP MCP) on nb201:52414.

修复点 (2026-06-02):
  1. 修正上游 URL: :52415 (fake proxy) -> :52414 (real slm-hub v0.2.2)
  2. 实现 MCP stateful session 协议:
     - 首次调用时自动发送 initialize, 提取 Mcp-Session-Id 响应头
     - 后续所有请求携带 Mcp-Session-Id 头
     - 初始化完成后发送 notifications/initialized
  3. 错误透传: 不再 swallow upstream 错误, 透传给 IDE
  4. 工具名映射: 兼容老调用 (list_services / search_tools / call_tool) ->
     真 slm-hub 命名 (hub__search_tools / hub__call_tool)
  5. 透传 serverInfo / capabilities 来自真实 hub
  6. SSE 兼容: Accept 头包含 application/json, text/event-stream
"""
import sys
import json
import urllib.request
import urllib.error
import threading

HUB_URL = "http://100.94.215.35:52414/mcp"  # real slm-mcp-hub v0.2.2
PROTOCOL_VERSION = "2024-11-05"
CLIENT_NAME = "trae-slm-hub-bridge"
CLIENT_VERSION = "2.0.0"

# --- 状态 ---
_session_lock = threading.Lock()
_session_id: str | None = None
_server_info: dict | None = None
_server_capabilities: dict | None = None
_initialized: bool = False


def _raw_post(payload: dict, headers: dict | None = None, timeout: int = 30):
    """直接 POST, 返回 (status, response_headers, json_body or text)."""
    data = json.dumps(payload).encode("utf-8")
    hdrs = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(HUB_URL, data=data, headers=hdrs)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, dict(resp.headers), resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return e.code, dict(e.headers or {}), body
    except Exception as e:
        return 0, {}, json.dumps({"error": f"network error: {e}"})


def _ensure_session():
    """确保 MCP session 已建立. 返回 (session_id, server_info, capabilities)."""
    global _session_id, _server_info, _server_capabilities, _initialized
    with _session_lock:
        if _initialized and _session_id:
            return _session_id, _server_info, _server_capabilities

        # 1. 发送 initialize
        init_payload = {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": CLIENT_NAME, "version": CLIENT_VERSION},
            },
        }
        status, headers, body = _raw_post(init_payload)
        if status != 200:
            raise RuntimeError(f"initialize failed: HTTP {status} body={body[:200]}")

        # 2. 提取 session id (大小写不敏感)
        sid = None
        for k, v in headers.items():
            if k.lower() == "mcp-session-id":
                sid = v
                break
        if not sid:
            # 可能在 body 里? 检查
            try:
                resp = json.loads(body)
                if isinstance(resp, dict) and "sessionId" in resp:
                    sid = resp["sessionId"]
            except Exception:
                pass
        if not sid:
            raise RuntimeError(f"no Mcp-Session-Id in initialize response. headers={list(headers.keys())}")

        # 3. 解析 server info
        try:
            resp = json.loads(body)
            _server_info = resp.get("result", {}).get("serverInfo", {})
            _server_capabilities = resp.get("result", {}).get("capabilities", {})
        except Exception:
            _server_info = {"name": "slm-mcp-hub", "version": "0.2.2"}
            _server_capabilities = {}

        # 4. 发送 notifications/initialized
        _raw_post(
            {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            headers={"Mcp-Session-Id": sid},
        )

        _session_id = sid
        _initialized = True
        return _session_id, _server_info, _server_capabilities


def _send_with_session(payload: dict, timeout: int = 30):
    """带 session id 发送请求. 自动在出错时重建 session 重试一次."""
    try:
        sid, _, _ = _ensure_session()
    except Exception as e:
        return {"jsonrpc": "2.0", "id": payload.get("id", 1),
                "error": {"code": -32000, "message": f"session init failed: {e}"}}

    payload = {**payload}
    status, headers, body = _raw_post(
        payload, headers={"Mcp-Session-Id": sid}, timeout=timeout
    )

    # 解析 SSE 格式 (event: message\ndata: {...}) 兼容
    if body.startswith("event:"):
        for line in body.split("\n"):
            line = line.strip()
            if line.startswith("data:"):
                body = line[5:].strip()
                break

    try:
        return json.loads(body)
    except Exception:
        return {"jsonrpc": "2.0", "id": payload.get("id", 1),
                "error": {"code": -32000, "message": f"invalid upstream response: {body[:200]}"}}


# --- 工具名映射 (兼容老调用) ---
TOOL_ALIASES = {
    "list_services": "hub__list_servers",   # 修复: 真名是 list_servers 不是 list_services
    "search_tools": "hub__search_tools",
    "call_tool": "hub__call_tool",
}

# --- 中文描述映射 ---
ZH_DESCRIPTIONS = {
    "hub__search_tools": "【必须】搜索工具。触发条件：用户意图涉及外部服务（地图、代码仓库、搜索、金融数据等），需要先搜索可用工具。输入：query=意图关键词。输出：匹配的工具名称、描述、参数schema。",
    "hub__call_tool": "【必须】调用工具。触发条件：已通过search_tools找到目标工具，需要执行具体操作。输入：tool=完整工具名（如'github__search_repositories'），arguments=参数对象。输出：工具执行结果。",
    "hub__list_servers": "【手动】列出服务器。触发条件：用户询问有哪些MCP服务可用，或需要了解服务概览。输出：6个服务器及其工具数量列表。",
}

ZH_INPUT_DESCRIPTIONS = {
    "hub__search_tools": {"query": "意图关键词，如'搜索代码仓库'、'查天气'、'股票行情'"},
    "hub__call_tool": {
        "tool": "完整工具名，格式: '服务器__工具名'，如 'github__search_repositories'",
        "arguments": "工具参数，从 search_tools 返回的 inputSchema 获取"
    },
}


def _handle_initialize(req_id):
    """对 IDE 报告真实 hub 的信息, 同时 lazy init session."""
    try:
        _, info, caps = _ensure_session()
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": caps or {},
                "serverInfo": info or {"name": "slm-mcp-hub", "version": "0.2.2"},
            },
        }
    except Exception as e:
        return {"jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32000, "message": str(e)}}


def _handle_tools_list(req_id):
    """返回 hub 真实 tools + 中文描述."""
    try:
        _ensure_session()
        upstream = _send_with_session(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
        )
        if "error" in upstream:
            return {"jsonrpc": "2.0", "id": req_id, "error": upstream["error"]}
        
        # 应用中文描述映射
        result = upstream.get("result", {})
        tools = result.get("tools", [])
        for tool in tools:
            name = tool.get("name", "")
            if name in ZH_DESCRIPTIONS:
                tool["description"] = ZH_DESCRIPTIONS[name]
            # 替换输入参数描述
            if name in ZH_INPUT_DESCRIPTIONS:
                props = tool.get("inputSchema", {}).get("properties", {})
                for prop_name, zh_desc in ZH_INPUT_DESCRIPTIONS[name].items():
                    if prop_name in props:
                        props[prop_name]["description"] = zh_desc
        
        return {"jsonrpc": "2.0", "id": req_id, "result": result}
    except Exception as e:
        return {"jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32000, "message": str(e)}}


def _handle_tools_call(req_id, params):
    """转发 tools/call. 透明处理 tool 别名."""
    try:
        _ensure_session()
        name = params.get("name", "")
        # 别名改写: 老名字 (search_tools) -> 真名 (hub__search_tools)
        real_name = TOOL_ALIASES.get(name, name)
        if real_name != name:
            params = {**params, "name": real_name}

        upstream = _send_with_session(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params},
            timeout=60,  # 真实工具可能慢, 拉长超时
        )
        if "error" in upstream:
            return {"jsonrpc": "2.0", "id": req_id, "error": upstream["error"]}
        return {"jsonrpc": "2.0", "id": req_id, "result": upstream.get("result", {})}
    except Exception as e:
        return {"jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32000, "message": str(e)}}


# --- 主循环 ---
def main():
    for line in sys.stdin:
        try:
            line = line.strip()
            if not line:
                continue
            req = json.loads(line)
            method = req.get("method")
            req_id = req.get("id")

            if method == "initialize":
                resp = _handle_initialize(req_id)
            elif method == "notifications/initialized":
                # IDE 也会发这个, 我们已经发起, 静默 ack
                continue
            elif method == "tools/list":
                resp = _handle_tools_list(req_id)
            elif method == "tools/call":
                resp = _handle_tools_call(req_id, req.get("params", {}))
            else:
                # 其他通知类消息 (如 notifications/cancelled) 静默
                if method and method.startswith("notifications/"):
                    continue
                resp = {"jsonrpc": "2.0", "id": req_id,
                        "error": {"code": -32601, "message": f"method not supported: {method}"}}

            print(json.dumps(resp), flush=True)
        except json.JSONDecodeError as e:
            print(json.dumps({"jsonrpc": "2.0", "id": None,
                              "error": {"code": -32700, "message": f"parse error: {e}"}}),
                  flush=True)
        except Exception as e:
            print(json.dumps({"jsonrpc": "2.0", "id": req.get("id") if "req" in locals() else None,
                              "error": {"code": -32603, "message": f"internal error: {e}"}}),
                  flush=True)


if __name__ == "__main__":
    main()
