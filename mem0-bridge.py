#!/usr/bin/env python3
"""Bridge stdio <-> mem0-server (HTTP MCP) on 201:8765.

实现 MCP 协议, 连接远程 mem0-server 并提供记忆库工具:
  - memories_add: 添加记忆
  - memories_search: 搜索记忆
  - memories_get_all: 获取所有记忆
  - memories_batch_add: 批量添加记忆
  - auto_recall: 自动调取记忆 (每轮对话前)
  - auto_capture: 自动存储记忆 (每轮对话后)
"""
import sys
import json
import urllib.request
import urllib.error
import threading

MEM0_URL = "http://100.94.215.35:8765"
PROTOCOL_VERSION = "2024-11-05"
CLIENT_NAME = "trae-mem0-bridge"
CLIENT_VERSION = "1.0.0"
DEFAULT_USER_ID = "trae-z20503740"

# --- 状态 ---
_session_lock = threading.Lock()
_session_id: str | None = None
_initialized: bool = False


def _raw_request(method: str, path: str, data: dict | None = None, headers: dict | None = None, timeout: int = 30):
    """发送 HTTP 请求, 返回 (status, response_headers, json_body or text)."""
    url = MEM0_URL + path
    hdrs = {"Content-Type": "application/json", "Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    
    if data:
        req_data = json.dumps(data).encode("utf-8")
    else:
        req_data = None
    
    req = urllib.request.Request(url, data=req_data, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, dict(resp.headers), resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return e.code, dict(e.headers or {}), body
    except Exception as e:
        return 0, {}, json.dumps({"error": f"network error: {e}"})


def _json_request(method: str, path: str, data: dict | None = None, timeout: int = 30):
    """发送请求并返回 JSON 解析结果."""
    status, headers, body = _raw_request(method, path, data, timeout=timeout)
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return {"error": f"invalid JSON response: {body[:200]}", "status": status}


# --- MCP 工具实现 ---
def _memories_add(text: str, user_id: str | None = None, metadata: dict | None = None):
    """添加单条记忆."""
    payload = {"text": text}
    if user_id:
        payload["user_id"] = user_id
    if metadata:
        payload["metadata"] = metadata
    return _json_request("POST", "/api/v1/memories", payload)


def _memories_search(query: str, user_id: str | None = None, limit: int = 10):
    """搜索记忆."""
    payload = {"query": query, "limit": limit}
    if user_id:
        payload["filters"] = {"user_id": user_id}
    return _json_request("POST", "/api/v1/memories/search", payload)


def _memories_get_all(user_id: str | None = None, limit: int = 100):
    """获取所有记忆 - 使用 search API 替代有问题的 get_all."""
    # mem0-server 的 get_all API 有 bug，使用 search 替代
    # 使用空查询或通配符来获取所有记忆
    payload = {"query": "*", "limit": limit}
    if user_id:
        payload["filters"] = {"user_id": user_id}
    result = _json_request("POST", "/api/v1/memories/search", payload)
    # 转换格式以匹配 get_all 的预期输出
    if "results" in result:
        return {"results": result["results"], "count": result["count"], "user_id": user_id or DEFAULT_USER_ID}
    return result


def _memories_batch_add(conversations: list, user_id: str | None = None):
    """批量添加记忆."""
    results = []
    for conv in conversations:
        text = conv.get("text", "")
        metadata = conv.get("metadata", {})
        result = _memories_add(text, user_id, metadata)
        results.append(result)
    return {"results": results, "count": len(results)}


def _auto_recall(query: str, user_id: str | None = None, limit: int = 5, min_score: float = 0.1):
    """自动调取记忆 (语义检索)."""
    result = _memories_search(query, user_id, limit)
    if "results" in result:
        # 过滤低分结果
        filtered = [r for r in result.get("results", []) if r.get("score", 1.0) >= min_score]
        result["results"] = filtered
        result["count"] = len(filtered)
    return result


def _auto_capture(turn: str, user_id: str | None = None, tags: list | None = None):
    """自动存储记忆 (LLM 提取)."""
    metadata = {"source": "auto_capture", "timestamp": str(int(__import__("time").time()))}
    if tags:
        metadata["tags"] = tags
    return _memories_add(turn, user_id, metadata)


# --- MCP 协议处理 ---
def _handle_initialize(req_id):
    """处理 initialize 请求."""
    global _initialized, _session_id
    with _session_lock:
        _initialized = True
        _session_id = "trae-mem0-session"
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "result": {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "mem0-server-bridge", "version": CLIENT_VERSION},
        },
    }


def _handle_tools_list(req_id):
    """返回工具列表."""
    tools = [
        {
            "name": "memories_add",
            "description": "添加记忆。触发：用户明确要求记住某事，或对话中提取到重要事实（偏好、配置、决策）。输入：text=记忆内容。输出：记忆ID。",
            "inputSchema": {
                "type": "object",
                "properties": {"text": {"type": "string", "description": "记忆文本内容"}},
                "required": ["text"],
            },
        },
        {
            "name": "memories_search",
            "description": "搜索记忆。触发：需要查询历史信息时调用。输入：query=关键词。输出：匹配的记忆列表，openclaw来源+30%权重。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"},
                    "limit": {"type": "integer", "default": 5, "description": "返回数量上限"}
                },
                "required": ["query"],
            },
        },
        {
            "name": "memories_get_all",
            "description": "获取全部记忆。触发：用户要求查看所有记忆，或需要全面回顾历史。输出：用户的所有记忆列表。",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "memories_batch_add",
            "description": "批量添加记忆。触发：需要一次性存储多条记忆。输入：conversations=记忆数组。输出：添加结果。",
            "inputSchema": {
                "type": "object",
                "properties": {"conversations": {"type": "array", "description": "记忆内容数组"}},
                "required": ["conversations"],
            },
        },
        {
            "name": "auto_recall",
            "description": "【必须】每轮对话开始时调用。触发条件：收到用户消息后，生成回复前。目的：检索相关历史记忆，避免重复询问，保持上下文连贯。输入：query=用户消息。输出：top-k相关记忆。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "用户本轮消息"},
                    "limit": {"type": "integer", "default": 5, "description": "返回条数"},
                    "min_score": {"type": "number", "default": 0.1, "description": "分数阈值"},
                },
                "required": ["query"],
            },
        },
        {
            "name": "auto_capture",
            "description": "【必须】每轮对话结束时调用。触发条件：回复完成后，结束对话前。目的：持久化本轮对话中的事实（偏好、决策、配置），供未来检索。输入：turn=完整对话文本。",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "turn": {"type": "string", "description": "本轮对话文本，格式: 'User: ...\\nAssistant: ...'"},
                    "tags": {"type": "array", "description": "可选标签"},
                },
                "required": ["turn"],
            },
        },
    ]
    return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools}}


def _handle_tools_call(req_id, params):
    """处理工具调用."""
    name = params.get("name", "")
    args = params.get("arguments", {})
    user_id = args.get("user_id", DEFAULT_USER_ID)
    
    try:
        if name == "memories_add":
            result = _memories_add(args.get("text", ""), user_id, args.get("metadata"))
        elif name == "memories_search":
            result = _memories_search(args.get("query", ""), user_id, args.get("limit", 5))
        elif name == "memories_get_all":
            result = _memories_get_all(user_id, args.get("limit", 100))
        elif name == "memories_batch_add":
            result = _memories_batch_add(args.get("conversations", []), user_id)
        elif name == "auto_recall":
            result = _auto_recall(args.get("query", ""), user_id, args.get("limit", 5), args.get("min_score", 0.1))
        elif name == "auto_capture":
            result = _auto_capture(args.get("turn", ""), user_id, args.get("tags"))
        else:
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"tool not found: {name}"}}
        
        # MCP 工具调用返回格式
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"content": [{"type": "text", "text": json.dumps(result)}]},
        }
    except Exception as e:
        return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32000, "message": str(e)}}


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
                continue
            elif method == "tools/list":
                resp = _handle_tools_list(req_id)
            elif method == "tools/call":
                resp = _handle_tools_call(req_id, req.get("params", {}))
            elif method and method.startswith("notifications/"):
                continue
            else:
                resp = {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"method not supported: {method}"}}
            
            print(json.dumps(resp), flush=True)
        except json.JSONDecodeError as e:
            print(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": f"parse error: {e}"}}), flush=True)
        except Exception as e:
            print(json.dumps({"jsonrpc": "2.0", "id": req.get("id") if "req" in locals() else None, "error": {"code": -32603, "message": f"internal error: {e}"}}), flush=True)


if __name__ == "__main__":
    main()