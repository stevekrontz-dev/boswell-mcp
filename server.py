#!/usr/bin/env python3
"""
Boswell MCP Server - Gives Claude.ai direct access to Boswell v2.5 memory system.

This server exposes 12 tools that map to the Boswell API endpoints,
allowing Claude to search, recall, and commit memories directly.
"""

import json
import os
import sys
import httpx
from mcp.server import Server
from mcp.types import Tool, TextContent
from mcp.server.stdio import stdio_server

# Debug logging to stderr (won't break stdio protocol)
def log(msg):
    print(f"[BOSWELL-DEBUG] {msg}", file=sys.stderr, flush=True)

# Boswell API configuration - pulled from environment, Railway sets this
BOSWELL_API = os.environ.get('BOSWELL_API', 'http://localhost:8000/v2')
INTERNAL_SECRET = os.environ.get('INTERNAL_SECRET', '')
log(f"BOSWELL_API = {BOSWELL_API}")
log(f"INTERNAL_SECRET set: {bool(INTERNAL_SECRET)}")

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
            name="boswell_semantic_search",
            description="Semantic search using AI embeddings. Finds conceptually related memories even without exact keyword matches. Use for conceptual queries like 'decisions about architecture' or 'patent opportunities'.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Conceptual search query"
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
                    },
                    "force_branch": {
                        "type": "boolean",
                        "description": "Suppress routing warnings - use when intentionally committing to a branch despite mismatch"
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

        # TASK QUEUE OPERATIONS
        Tool(
            name="boswell_create_task",
            description="Create a new task in the queue. Use to spawn subtasks or add work for yourself or other agents.",
            inputSchema={
                "type": "object",
                "properties": {
                    "description": {"type": "string", "description": "What needs to be done"},
                    "branch": {"type": "string", "description": "Which branch this relates to (command-center, tint-atlanta, etc.)"},
                    "priority": {"type": "integer", "description": "Priority 1-10 (1=highest, default=5)"},
                    "assigned_to": {"type": "string", "description": "Optional: assign to specific instance"},
                    "metadata": {"type": "object", "description": "Optional: additional context"}
                },
                "required": ["description"]
            }
        ),
        Tool(
            name="boswell_claim_task",
            description="Claim a task for this agent instance. Prevents other agents from working on it. Use when starting work on a task from the queue.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID to claim"},
                    "instance_id": {"type": "string", "description": "Your unique instance identifier (e.g., 'CC1', 'CW-PM')"}
                },
                "required": ["task_id", "instance_id"]
            }
        ),
        Tool(
            name="boswell_release_task",
            description="Release a claimed task. Use 'completed' when done, 'blocked' if stuck, 'manual' to unclaim without status change.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID to release"},
                    "instance_id": {"type": "string", "description": "Your instance identifier"},
                    "reason": {"type": "string", "enum": ["completed", "blocked", "timeout", "manual"], "description": "Why releasing (default: manual)"}
                },
                "required": ["task_id", "instance_id"]
            }
        ),
        Tool(
            name="boswell_update_task",
            description="Update a task's fields (description, status, priority, metadata). Use to report progress or modify task details.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID to update"},
                    "status": {"type": "string", "enum": ["open", "claimed", "blocked", "done"], "description": "New status"},
                    "description": {"type": "string", "description": "Updated description"},
                    "priority": {"type": "integer", "description": "Priority (1=highest)"},
                    "metadata": {"type": "object", "description": "Additional metadata to merge"}
                },
                "required": ["task_id"]
            }
        ),
        Tool(
            name="boswell_delete_task",
            description="Soft delete a task (sets status to 'deleted'). Use to clean up completed or cancelled tasks from the queue.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID to delete"}
                },
                "required": ["task_id"]
            }
        ),
        Tool(
            name="boswell_halt_tasks",
            description="EMERGENCY STOP - Halt all task processing. Blocks all claimed tasks, prevents new claims. Use when swarm behavior is problematic.",
            inputSchema={
                "type": "object",
                "properties": {
                    "reason": {"type": "string", "description": "Why halting (default: 'Manual emergency halt')"}
                }
            }
        ),
        Tool(
            name="boswell_resume_tasks",
            description="Resume task processing after a halt. Clears the halt flag and allows new claims.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="boswell_halt_status",
            description="Check if the task system is currently halted.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),

        # TRAILS (Memory Path Tracking)
        Tool(
            name="boswell_record_trail",
            description="Record a traversal between two memories. Strengthens the path for future recall.",
            inputSchema={
                "type": "object",
                "properties": {
                    "source_blob": {"type": "string", "description": "Source memory blob hash"},
                    "target_blob": {"type": "string", "description": "Target memory blob hash"}
                },
                "required": ["source_blob", "target_blob"]
            }
        ),
        Tool(
            name="boswell_hot_trails",
            description="Get the strongest memory trails, sorted by strength. These are frequently traversed paths.",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Max trails to return (default: 20)"}
                }
            }
        ),
        Tool(
            name="boswell_trails_from",
            description="Get outbound trails from a specific memory. Shows what memories are often accessed after this one.",
            inputSchema={
                "type": "object",
                "properties": {
                    "blob": {"type": "string", "description": "Source memory blob hash"}
                },
                "required": ["blob"]
            }
        ),
        Tool(
            name="boswell_trails_to",
            description="Get inbound trails to a specific memory. Shows what memories often lead to this one.",
            inputSchema={
                "type": "object",
                "properties": {
                    "blob": {"type": "string", "description": "Target memory blob hash"}
                },
                "required": ["blob"]
            }
        ),
    ]


# ==================== TOOL HANDLERS ====================

@app.call_tool()
async def call_tool(name: str, arguments: dict):
    """Handle tool calls by proxying to Boswell API."""
    log(f"TOOL CALL START: {name} with args: {arguments}")

    # Build headers - include internal secret for stdio auth bypass
    headers = {}
    if INTERNAL_SECRET:
        headers['X-Boswell-Internal'] = INTERNAL_SECRET

    async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
        try:
            log(f"Making request to {BOSWELL_API} for tool: {name}")
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

            elif name == "boswell_semantic_search":
                params = {"q": arguments["query"]}
                if "limit" in arguments:
                    params["limit"] = arguments["limit"]
                resp = await client.get(f"{BOSWELL_API}/semantic-search", params=params)

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
                if arguments.get("force_branch"):
                    payload["force_branch"] = True
                resp = await client.post(f"{BOSWELL_API}/commit", json=payload)

                # Phase 5: Surface routing warnings
                if resp.status_code in (200, 201):
                    data = resp.json()
                    if "routing_suggestion" in data:
                        rs = data["routing_suggestion"]
                        warning = f"\n\nROUTING WARNING: {rs['message']}\nAdd force_branch=true to suppress."
                        return [TextContent(type="text", text=json.dumps(data, indent=2) + warning)]

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

            elif name == "boswell_create_task":
                payload = {"description": arguments["description"]}
                for field in ["branch", "priority", "assigned_to", "metadata"]:
                    if field in arguments:
                        payload[field] = arguments[field]
                resp = await client.post(f"{BOSWELL_API}/tasks", json=payload)

            elif name == "boswell_claim_task":
                payload = {"instance_id": arguments["instance_id"]}
                resp = await client.post(f"{BOSWELL_API}/tasks/{arguments['task_id']}/claim", json=payload)

            elif name == "boswell_release_task":
                payload = {
                    "instance_id": arguments["instance_id"],
                    "reason": arguments.get("reason", "manual")
                }
                resp = await client.post(f"{BOSWELL_API}/tasks/{arguments['task_id']}/release", json=payload)

            elif name == "boswell_update_task":
                payload = {}
                for field in ["status", "description", "priority", "metadata"]:
                    if field in arguments:
                        payload[field] = arguments[field]
                resp = await client.patch(f"{BOSWELL_API}/tasks/{arguments['task_id']}", json=payload)

            elif name == "boswell_delete_task":
                resp = await client.delete(f"{BOSWELL_API}/tasks/{arguments['task_id']}")

            elif name == "boswell_halt_tasks":
                payload = {}
                if "reason" in arguments:
                    payload["reason"] = arguments["reason"]
                resp = await client.post(f"{BOSWELL_API}/tasks/halt", json=payload)

            elif name == "boswell_resume_tasks":
                resp = await client.post(f"{BOSWELL_API}/tasks/resume", json={})

            elif name == "boswell_halt_status":
                resp = await client.get(f"{BOSWELL_API}/tasks/halt-status")

            # TRAILS
            elif name == "boswell_record_trail":
                payload = {
                    "source_blob": arguments["source_blob"],
                    "target_blob": arguments["target_blob"]
                }
                resp = await client.post(f"{BOSWELL_API}/trails/record", json=payload)

            elif name == "boswell_hot_trails":
                params = {}
                if "limit" in arguments:
                    params["limit"] = arguments["limit"]
                resp = await client.get(f"{BOSWELL_API}/trails/hot", params=params)

            elif name == "boswell_trails_from":
                resp = await client.get(f"{BOSWELL_API}/trails/from/{arguments['blob']}")

            elif name == "boswell_trails_to":
                resp = await client.get(f"{BOSWELL_API}/trails/to/{arguments['blob']}")

            else:
                log(f"Unknown tool: {name}")
                return [TextContent(type="text", text=f"Unknown tool: {name}")]

            # Format response
            log(f"Got response: status={resp.status_code}")
            if resp.status_code == 200 or resp.status_code == 201:
                try:
                    data = resp.json()
                    log(f"Returning success response for {name}")
                    return [TextContent(type="text", text=json.dumps(data, indent=2))]
                except:
                    log(f"Returning raw text response for {name}")
                    return [TextContent(type="text", text=resp.text)]
            else:
                log(f"Returning error response: {resp.status_code}")
                return [TextContent(type="text", text=f"Error {resp.status_code}: {resp.text}")]

        except httpx.TimeoutException:
            log(f"TIMEOUT for tool {name}")
            return [TextContent(type="text", text="Error: Request to Boswell API timed out")]
        except Exception as e:
            log(f"EXCEPTION for tool {name}: {str(e)}")
            return [TextContent(type="text", text=f"Error: {str(e)}")]


# ==================== MAIN ====================

async def main():
    """Run the MCP server via stdio."""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
