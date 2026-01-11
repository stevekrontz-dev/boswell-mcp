#!/usr/bin/env python3
"""
Boswell MCP HTTP Server - Remote MCP server for Claude.ai Custom Connectors.

Implements MCP protocol with SSE transport for remote connections.
"""

import json
import asyncio
import uuid
import os
from typing import Any, Dict
import httpx
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from sse_starlette.sse import EventSourceResponse

# Boswell API configuration - Railway deployment
BOSWELL_API = "https://delightful-imagination-production-f6a1.up.railway.app/v2"

# Store for SSE sessions - maps session_id to response queue
sessions: Dict[str, asyncio.Queue] = {}

# Tool definitions
TOOLS = [
    {
        "name": "boswell_brief",
        "description": "Get a quick context brief of current Boswell state - recent commits, pending sessions, all branches. Use this at conversation start to understand what's been happening.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "branch": {
                    "type": "string",
                    "description": "Branch to focus on (default: command-center)",
                    "default": "command-center"
                }
            }
        }
    },
    {
        "name": "boswell_branches",
        "description": "List all cognitive branches in Boswell. Branches are: tint-atlanta (CRM/business), iris (research/BCI), tint-empire (franchise), family (personal), command-center (infrastructure), boswell (memory system).",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "boswell_head",
        "description": "Get the current HEAD commit for a specific branch.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "branch": {"type": "string", "description": "Branch name"}
            },
            "required": ["branch"]
        }
    },
    {
        "name": "boswell_log",
        "description": "Get commit history for a branch. Shows what memories have been recorded.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "branch": {"type": "string", "description": "Branch name"},
                "limit": {"type": "integer", "description": "Max commits (default: 10)", "default": 10}
            },
            "required": ["branch"]
        }
    },
    {
        "name": "boswell_search",
        "description": "Search memories across all branches by keyword. Returns matching content with commit info.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "branch": {"type": "string", "description": "Optional: limit to branch"},
                "limit": {"type": "integer", "description": "Max results (default: 10)", "default": 10}
            },
            "required": ["query"]
        }
    },
    {
        "name": "boswell_recall",
        "description": "Recall a specific memory by its blob hash or commit hash.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "hash": {"type": "string", "description": "Blob hash"},
                "commit": {"type": "string", "description": "Or commit hash"}
            }
        }
    },
    {
        "name": "boswell_links",
        "description": "List resonance links between memories. Shows cross-branch connections.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "branch": {"type": "string", "description": "Optional: filter by branch"},
                "link_type": {"type": "string", "description": "Optional: resonance, causal, etc."}
            }
        }
    },
    {
        "name": "boswell_graph",
        "description": "Get the full memory graph - all nodes and edges.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "boswell_reflect",
        "description": "Get AI-surfaced insights - highly connected memories and patterns.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "boswell_commit",
        "description": "Commit a new memory to Boswell. Preserves important decisions and context.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "branch": {"type": "string", "description": "Branch to commit to"},
                "content": {"type": "object", "description": "Memory content as JSON"},
                "message": {"type": "string", "description": "Commit message"},
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Optional tags"}
            },
            "required": ["branch", "content", "message"]
        }
    },
    {
        "name": "boswell_link",
        "description": "Create a resonance link between two memories across branches.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source_blob": {"type": "string"},
                "target_blob": {"type": "string"},
                "source_branch": {"type": "string"},
                "target_branch": {"type": "string"},
                "link_type": {"type": "string", "default": "resonance"},
                "reasoning": {"type": "string", "description": "Why connected"}
            },
            "required": ["source_blob", "target_blob", "source_branch", "target_branch", "reasoning"]
        }
    },
    {
        "name": "boswell_checkout",
        "description": "Switch focus to a different cognitive branch.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "branch": {"type": "string", "description": "Branch to check out"}
            },
            "required": ["branch"]
        }
    },
    {
        "name": "boswell_startup",
        "description": "Load startup context in ONE call. Returns sacred_manifest (active commitments) + tool_registry (available tools). Call this FIRST at the start of every conversation.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
]


async def call_boswell_tool(name: str, arguments: dict) -> dict:
    """Execute a Boswell tool and return result."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            if name == "boswell_brief":
                branch = arguments.get("branch", "command-center")
                resp = await client.get(f"{BOSWELL_API}/quick-brief", params={"branch": branch})

            elif name == "boswell_branches":
                resp = await client.get(f"{BOSWELL_API}/branches")

            elif name == "boswell_head":
                resp = await client.get(f"{BOSWELL_API}/head", params={"branch": arguments["branch"]})

            elif name == "boswell_log":
                params = {"branch": arguments["branch"]}
                if "limit" in arguments:
                    params["limit"] = arguments["limit"]
                resp = await client.get(f"{BOSWELL_API}/log", params=params)

            elif name == "boswell_search":
                params = {"q": arguments["query"]}
                if "branch" in arguments:
                    params["branch"] = arguments["branch"]
                if "limit" in arguments:
                    params["limit"] = arguments["limit"]
                resp = await client.get(f"{BOSWELL_API}/search", params=params)

            elif name == "boswell_recall":
                params = {}
                if "hash" in arguments:
                    params["hash"] = arguments["hash"]
                if "commit" in arguments:
                    params["commit"] = arguments["commit"]
                resp = await client.get(f"{BOSWELL_API}/recall", params=params)

            elif name == "boswell_links":
                params = {}
                if "branch" in arguments:
                    params["branch"] = arguments["branch"]
                if "link_type" in arguments:
                    params["link_type"] = arguments["link_type"]
                resp = await client.get(f"{BOSWELL_API}/links", params=params)

            elif name == "boswell_graph":
                resp = await client.get(f"{BOSWELL_API}/graph")

            elif name == "boswell_reflect":
                resp = await client.get(f"{BOSWELL_API}/reflect")

            elif name == "boswell_commit":
                payload = {
                    "branch": arguments["branch"],
                    "content": arguments["content"],
                    "message": arguments["message"],
                    "author": "claude-web",
                    "type": "memory"
                }
                if "tags" in arguments:
                    payload["tags"] = arguments["tags"]
                resp = await client.post(f"{BOSWELL_API}/commit", json=payload)

            elif name == "boswell_link":
                payload = {
                    "source_blob": arguments["source_blob"],
                    "target_blob": arguments["target_blob"],
                    "source_branch": arguments["source_branch"],
                    "target_branch": arguments["target_branch"],
                    "link_type": arguments.get("link_type", "resonance"),
                    "reasoning": arguments["reasoning"],
                    "created_by": "claude-web"
                }
                resp = await client.post(f"{BOSWELL_API}/link", json=payload)

            elif name == "boswell_checkout":
                resp = await client.post(f"{BOSWELL_API}/checkout", json={"branch": arguments["branch"]})

            elif name == "boswell_startup":
                # Fetch sacred_manifest and tool_registry in one call
                startup_data = {"sacred_manifest": None, "tool_registry": None, "errors": []}

                # Search for sacred_manifest - get multiple results and find the actual manifest
                manifest_resp = await client.get(f"{BOSWELL_API}/search", params={"q": "sacred_manifest", "limit": 5})
                if manifest_resp.status_code == 200:
                    manifest_results = manifest_resp.json()
                    for result in manifest_results.get("results", []):
                        blob_hash = result.get("blob_hash")
                        if blob_hash:
                            recall_resp = await client.get(f"{BOSWELL_API}/recall", params={"hash": blob_hash})
                            if recall_resp.status_code == 200:
                                recall_data = recall_resp.json()
                                try:
                                    content = json.loads(recall_data.get("content", "{}"))
                                    # Check if this is the actual sacred_manifest (not a session log mentioning it)
                                    if content.get("type") == "sacred_manifest":
                                        startup_data["sacred_manifest"] = content
                                        break
                                except:
                                    pass
                else:
                    startup_data["errors"].append(f"Failed to search sacred_manifest: {manifest_resp.status_code}")

                # Search for tool_registry - get multiple results and find the actual registry
                registry_resp = await client.get(f"{BOSWELL_API}/search", params={"q": "tool_registry", "limit": 5})
                if registry_resp.status_code == 200:
                    registry_results = registry_resp.json()
                    for result in registry_results.get("results", []):
                        blob_hash = result.get("blob_hash")
                        if blob_hash:
                            recall_resp = await client.get(f"{BOSWELL_API}/recall", params={"hash": blob_hash})
                            if recall_resp.status_code == 200:
                                recall_data = recall_resp.json()
                                try:
                                    content = json.loads(recall_data.get("content", "{}"))
                                    # Check if this is the actual tool_registry (not a session log mentioning it)
                                    if content.get("type") == "tool_registry":
                                        startup_data["tool_registry"] = content
                                        break
                                except:
                                    pass
                else:
                    startup_data["errors"].append(f"Failed to search tool_registry: {registry_resp.status_code}")

                # Clean up errors if empty
                if not startup_data["errors"]:
                    del startup_data["errors"]

                return startup_data

            else:
                return {"error": f"Unknown tool: {name}"}

            if resp.status_code in (200, 201):
                return resp.json()
            else:
                return {"error": f"HTTP {resp.status_code}", "details": resp.text}

        except Exception as e:
            return {"error": str(e)}


async def process_mcp_request(body: dict) -> dict:
    """Process an MCP JSON-RPC request and return response."""
    method = body.get("method", "")
    params = body.get("params", {})
    request_id = body.get("id")

    if method == "initialize":
        result = {
            "protocolVersion": "2024-11-05",
            "serverInfo": {
                "name": "boswell-mcp",
                "version": "1.0.0"
            },
            "capabilities": {
                "tools": {}
            }
        }

    elif method == "notifications/initialized":
        # Client confirms initialization - no response needed
        return None

    elif method == "tools/list":
        result = {"tools": TOOLS}

    elif method == "tools/call":
        tool_name = params.get("name")
        arguments = params.get("arguments", {})
        tool_result = await call_boswell_tool(tool_name, arguments)
        result = {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(tool_result, indent=2)
                }
            ]
        }

    elif method == "ping":
        result = {}

    else:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"Unknown method: {method}"}
        }

    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "result": result
    }


# ==================== MCP SSE TRANSPORT ====================

async def handle_sse(request: Request):
    """
    SSE endpoint for MCP transport.
    Sends an 'endpoint' event with the message URL, then streams responses.
    """
    session_id = str(uuid.uuid4())
    queue = asyncio.Queue()
    sessions[session_id] = queue

    # Get base URL from request, ensuring HTTPS
    base_url = str(request.base_url).rstrip('/')
    # Railway/proxies use X-Forwarded-Proto, force HTTPS
    if base_url.startswith("http://"):
        base_url = "https://" + base_url[7:]
    message_endpoint = f"{base_url}/messages/{session_id}"

    async def event_generator():
        try:
            # First, send the endpoint event telling client where to POST
            yield {
                "event": "endpoint",
                "data": message_endpoint
            }

            # Keep connection alive and stream responses
            while True:
                try:
                    # Wait for messages with timeout for keepalive
                    message = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield {
                        "event": "message",
                        "data": json.dumps(message)
                    }
                except asyncio.TimeoutError:
                    # Send keepalive ping
                    yield {"event": "ping", "data": ""}

        except asyncio.CancelledError:
            pass
        finally:
            # Cleanup session
            sessions.pop(session_id, None)

    return EventSourceResponse(event_generator())


async def handle_messages(request: Request):
    """
    Handle POST requests from the MCP client.
    Processes the request and queues the response for SSE delivery.
    """
    # Extract session_id from path
    session_id = request.path_params.get("session_id")

    if session_id not in sessions:
        return JSONResponse(
            {"error": "Session not found. Connect to /sse first."},
            status_code=404
        )

    try:
        body = await request.json()
    except:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    # Process the request
    response = await process_mcp_request(body)

    # Queue the response for SSE delivery
    if response is not None:
        await sessions[session_id].put(response)

    # Return accepted
    return Response(status_code=202)


async def handle_mcp_post(request: Request):
    """Handle direct MCP JSON-RPC requests (non-SSE fallback)."""
    try:
        body = await request.json()
    except:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    response = await process_mcp_request(body)
    if response is None:
        return Response(status_code=204)
    return JSONResponse(response)


async def health_check(request: Request):
    """Health check endpoint."""
    return JSONResponse({
        "status": "ok",
        "server": "boswell-mcp",
        "version": "1.0.0",
        "tools": len(TOOLS),
        "active_sessions": len(sessions)
    })


async def api_quick_brief(request: Request):
    """Direct HTTP endpoint for quick-brief - used by CC for recovery context."""
    branch = request.query_params.get("branch", "command-center")
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.get(f"{BOSWELL_API}/quick-brief", params={"branch": branch})
            if resp.status_code == 200:
                return JSONResponse(resp.json())
            else:
                return JSONResponse({"error": f"HTTP {resp.status_code}", "details": resp.text}, status_code=resp.status_code)
        except Exception as e:
            return JSONResponse({"error": str(e)}, status_code=500)


# ==================== APP ====================

app = Starlette(
    debug=False,
    routes=[
        Route("/", health_check, methods=["GET"]),
        Route("/health", health_check, methods=["GET"]),
        Route("/api/quick-brief", api_quick_brief, methods=["GET"]),
        Route("/mcp", handle_mcp_post, methods=["POST"]),
        Route("/sse", handle_sse, methods=["GET"]),
        Route("/messages/{session_id}", handle_messages, methods=["POST"]),
    ]
)


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
