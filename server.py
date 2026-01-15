#!/usr/bin/env python3
"""
Boswell MCP Server - Gives Claude.ai direct access to Boswell v2.5 memory system.

This server exposes 12 tools that map to the Boswell API endpoints,
allowing Claude to search, recall, and commit memories directly.
"""

import json
import httpx
from mcp.server import Server
from mcp.types import Tool, TextContent
from mcp.server.stdio import stdio_server

# Boswell API configuration
BOSWELL_API = "https://stevekrontz.com/boswell/v2"

# Initialize MCP server
app = Server("boswell-mcp")


# ==================== TOOL DEFINITIONS ====================

@app.list_tools()
async def list_tools():
    """Return list of available Boswell tools."""
    return [
        # READ OPERATIONS
        Tool(
            name="boswell_brief",
            description="Get a quick context brief of current Boswell state - recent commits, pending sessions, all branches. Use this at conversation start to understand what's been happening.",
            inputSchema={
                "type": "object",
                "properties": {
                    "branch": {
                        "type": "string",
                        "description": "Branch to focus on (default: command-center)",
                        "default": "command-center"
                    }
                }
            }
        ),
        Tool(
            name="boswell_branches",
            description="List all cognitive branches in Boswell. Branches are: tint-atlanta (CRM/business), iris (research/BCI), tint-empire (franchise), family (personal), command-center (infrastructure), boswell (memory system).",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="boswell_head",
            description="Get the current HEAD commit for a specific branch.",
            inputSchema={
                "type": "object",
                "properties": {
                    "branch": {
                        "type": "string",
                        "description": "Branch name (e.g., tint-atlanta, command-center, boswell)"
                    }
                },
                "required": ["branch"]
            }
        ),
        Tool(
            name="boswell_log",
            description="Get commit history for a branch. Shows what memories have been recorded.",
            inputSchema={
                "type": "object",
                "properties": {
                    "branch": {
                        "type": "string",
                        "description": "Branch name"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max commits to return (default: 10)",
                        "default": 10
                    }
                },
                "required": ["branch"]
            }
        ),
        Tool(
            name="boswell_search",
            description="Search memories across all branches by keyword. Returns matching content with commit info.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query"
                    },
                    "branch": {
                        "type": "string",
                        "description": "Optional: limit search to specific branch"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results (default: 10)",
                        "default": 10
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="boswell_recall",
            description="Recall a specific memory by its blob hash or commit hash.",
            inputSchema={
                "type": "object",
                "properties": {
                    "hash": {
                        "type": "string",
                        "description": "Blob hash to recall"
                    },
                    "commit": {
                        "type": "string",
                        "description": "Or commit hash to recall"
                    }
                }
            }
        ),
        Tool(
            name="boswell_links",
            description="List resonance links between memories. Shows cross-branch connections.",
            inputSchema={
                "type": "object",
                "properties": {
                    "branch": {
                        "type": "string",
                        "description": "Optional: filter by branch"
                    },
                    "link_type": {
                        "type": "string",
                        "description": "Optional: filter by type (resonance, causal, contradiction, elaboration, application)"
                    }
                }
            }
        ),
        Tool(
            name="boswell_graph",
            description="Get the full memory graph - all nodes (memories) and edges (links). Useful for understanding the topology.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="boswell_reflect",
            description="Get AI-surfaced insights - highly connected memories and cross-branch patterns.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),

        # WRITE OPERATIONS
        Tool(
            name="boswell_commit",
            description="Commit a new memory to Boswell. Use this to preserve important decisions, insights, or context worth remembering.",
            inputSchema={
                "type": "object",
                "properties": {
                    "branch": {
                        "type": "string",
                        "description": "Branch to commit to (tint-atlanta, iris, tint-empire, family, command-center, boswell)"
                    },
                    "content": {
                        "type": "object",
                        "description": "Memory content as JSON object"
                    },
                    "message": {
                        "type": "string",
                        "description": "Commit message describing the memory"
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional tags for categorization"
                    }
                },
                "required": ["branch", "content", "message"]
            }
        ),
        Tool(
            name="boswell_link",
            description="Create a resonance link between two memories across branches. Links capture conceptual connections.",
            inputSchema={
                "type": "object",
                "properties": {
                    "source_blob": {
                        "type": "string",
                        "description": "Source memory blob hash"
                    },
                    "target_blob": {
                        "type": "string",
                        "description": "Target memory blob hash"
                    },
                    "source_branch": {
                        "type": "string",
                        "description": "Source branch name"
                    },
                    "target_branch": {
                        "type": "string",
                        "description": "Target branch name"
                    },
                    "link_type": {
                        "type": "string",
                        "description": "Type: resonance, causal, contradiction, elaboration, application",
                        "default": "resonance"
                    },
                    "reasoning": {
                        "type": "string",
                        "description": "Why these memories are connected"
                    }
                },
                "required": ["source_blob", "target_blob", "source_branch", "target_branch", "reasoning"]
            }
        ),
        Tool(
            name="boswell_checkout",
            description="Switch focus to a different cognitive branch.",
            inputSchema={
                "type": "object",
                "properties": {
                    "branch": {
                        "type": "string",
                        "description": "Branch to check out"
                    }
                },
                "required": ["branch"]
            }
        ),
        Tool(
            name="boswell_startup",
            description="Load startup context. Returns commitments + semantically relevant memories. Call FIRST every conversation.",
            inputSchema={
                "type": "object",
                "properties": {
                    "context": {
                        "type": "string",
                        "description": "Optional context for semantic retrieval (default: 'important decisions and active commitments')"
                    },
                    "k": {
                        "type": "integer",
                        "description": "Number of relevant memories to return (default: 5)",
                        "default": 5
                    }
                }
            }
        ),
    ]


# ==================== TOOL HANDLERS ====================

@app.call_tool()
async def call_tool(name: str, arguments: dict):
    """Handle tool calls by proxying to Boswell API."""

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
                # v3: Use semantic startup endpoint for contextually relevant memories
                context = arguments.get("context", "important decisions and active commitments")
                k = arguments.get("k", 5)
                resp = await client.get(
                    f"{BOSWELL_API}/startup",
                    params={"context": context, "k": k}
                )
                if resp.status_code == 200:
                    return [TextContent(type="text", text=json.dumps(resp.json(), indent=2))]
                else:
                    return [TextContent(type="text", text=f"Error {resp.status_code}: {resp.text}")]

            else:
                return [TextContent(type="text", text=f"Unknown tool: {name}")]

            # Format response
            if resp.status_code == 200 or resp.status_code == 201:
                try:
                    data = resp.json()
                    return [TextContent(type="text", text=json.dumps(data, indent=2))]
                except:
                    return [TextContent(type="text", text=resp.text)]
            else:
                return [TextContent(type="text", text=f"Error {resp.status_code}: {resp.text}")]

        except httpx.TimeoutException:
            return [TextContent(type="text", text="Error: Request to Boswell API timed out")]
        except Exception as e:
            return [TextContent(type="text", text=f"Error: {str(e)}")]


# ==================== MAIN ====================

async def main():
    """Run the MCP server via stdio."""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
