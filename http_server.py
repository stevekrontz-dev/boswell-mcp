#!/usr/bin/env python3
"""
Boswell MCP HTTP Server - Remote MCP server for Claude.ai Custom Connectors.

This wraps the MCP server with HTTP transport using Server-Sent Events (SSE)
as required by the MCP protocol for remote connections.
"""

import json
import asyncio
from typing import Any
import httpx
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from sse_starlette.sse import EventSourceResponse

# Boswell API configuration
BOSWELL_API = "https://stevekrontz.com/boswell/v2"

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

            else:
                return {"error": f"Unknown tool: {name}"}

            if resp.status_code in (200, 201):
                return resp.json()
            else:
                return {"error": f"HTTP {resp.status_code}", "details": resp.text}

        except Exception as e:
            return {"error": str(e)}


# ==================== MCP HTTP ENDPOINTS ====================

async def handle_mcp_sse(request: Request):
    """Handle MCP requests via Server-Sent Events."""

    async def event_generator():
        # Send server info
        yield {
            "event": "message",
            "data": json.dumps({
                "jsonrpc": "2.0",
                "method": "server/info",
                "params": {
                    "name": "boswell-mcp",
                    "version": "1.0.0",
                    "capabilities": {
                        "tools": {}
                    }
                }
            })
        }

    return EventSourceResponse(event_generator())


async def handle_mcp_post(request: Request):
    """Handle MCP JSON-RPC requests."""
    try:
        body = await request.json()
    except:
        return JSONResponse({"error": "Invalid JSON"}, status_code=400)

    method = body.get("method", "")
    params = body.get("params", {})
    request_id = body.get("id")

    # Handle different MCP methods
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
        return JSONResponse({
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"Unknown method: {method}"}
        })

    return JSONResponse({
        "jsonrpc": "2.0",
        "id": request_id,
        "result": result
    })


async def health_check(request: Request):
    """Health check endpoint."""
    return JSONResponse({
        "status": "ok",
        "server": "boswell-mcp",
        "version": "1.0.0",
        "tools": len(TOOLS)
    })


# ==================== APP ====================

app = Starlette(
    debug=False,
    routes=[
        Route("/", health_check, methods=["GET"]),
        Route("/health", health_check, methods=["GET"]),
        Route("/mcp", handle_mcp_post, methods=["POST"]),
        Route("/sse", handle_mcp_sse, methods=["GET"]),
    ]
)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
