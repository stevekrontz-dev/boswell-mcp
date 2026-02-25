#!/usr/bin/env python3
"""
Boswell MCP Server - Persistent memory for Claude instances.

Supports authentication via:
  - BOSWELL_API_KEY (recommended for external users)
  - INTERNAL_SECRET (Steve's stdio bypass)

Usage:
  boswell serve          # via CLI
  python -m boswell_mcp  # via module
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
    print(f"[BOSWELL] {msg}", file=sys.stderr, flush=True)


# Configuration from environment
BOSWELL_API = os.environ.get('BOSWELL_API', 'http://localhost:8000/v2')
BOSWELL_API_KEY = os.environ.get('BOSWELL_API_KEY', '')
INTERNAL_SECRET = os.environ.get('INTERNAL_SECRET', '')

log(f"BOSWELL_API = {BOSWELL_API}")
log(f"Auth: {'API_KEY' if BOSWELL_API_KEY else 'INTERNAL_SECRET' if INTERNAL_SECRET else 'NONE'}")


def _build_headers() -> dict:
    """Build auth headers. API key takes priority over internal secret."""
    headers = {}
    if BOSWELL_API_KEY:
        headers['X-API-Key'] = BOSWELL_API_KEY
    elif INTERNAL_SECRET:
        headers['X-Boswell-Internal'] = INTERNAL_SECRET
    return headers


# Initialize MCP server
app = Server("boswell-mcp")


# ==================== TOOL DEFINITIONS ====================

@app.list_tools()
async def list_tools():
    """Return list of available Boswell tools."""
    return [
        # READ OPERATIONS
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
                    },
                    "verbosity": {
                        "type": "string",
                        "enum": ["minimal", "normal", "full"],
                        "description": "Response size: minimal (greeting), normal (work), full (debug)",
                        "default": "normal"
                    }
                }
            }
        ),
        Tool(
            name="boswell_brief",
            description="Quick context snapshot—recent commits, open tasks, branch activity. Call when resuming work or when asked 'what's been happening?' Lighter than boswell_startup.",
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
            description="List all cognitive branches: command-center (infrastructure), tint-atlanta (CRM), iris (research), tint-empire (franchise), family (personal), boswell (memory system). Use to understand the topology.",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="boswell_head",
            description="Get the current HEAD commit for a branch. Use to check what was last committed.",
            inputSchema={
                "type": "object",
                "properties": {
                    "branch": {"type": "string", "description": "Branch name (e.g., tint-atlanta, command-center, boswell)"}
                },
                "required": ["branch"]
            }
        ),
        Tool(
            name="boswell_log",
            description="View commit history for a branch. Use to trace what happened, find specific decisions, or understand work progression.",
            inputSchema={
                "type": "object",
                "properties": {
                    "branch": {"type": "string", "description": "Branch name"},
                    "limit": {"type": "integer", "description": "Max commits to return (default: 10)", "default": 10}
                },
                "required": ["branch"]
            }
        ),
        Tool(
            name="boswell_search",
            description="Keyword search across all memories. Call BEFORE answering questions about past work when immediate context is missing. If asked 'what were we doing?' and you don't know, search first.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "branch": {"type": "string", "description": "Optional: limit search to specific branch"},
                    "limit": {"type": "integer", "description": "Max results (default: 10)", "default": 10}
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="boswell_semantic_search",
            description="Find conceptually related memories using AI embeddings. Use for fuzzy queries like 'decisions about architecture' or when keyword search misses context. Complements boswell_search.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Conceptual search query"},
                    "limit": {"type": "integer", "description": "Max results (default: 10)", "default": 10}
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="boswell_recall",
            description="Retrieve a specific memory by its blob hash or commit hash. Use when you have a hash reference and need full content.",
            inputSchema={
                "type": "object",
                "properties": {
                    "hash": {"type": "string", "description": "Blob hash to recall"},
                    "commit": {"type": "string", "description": "Or commit hash to recall"}
                }
            }
        ),
        Tool(
            name="boswell_links",
            description="List resonance links between memories. Use to see cross-branch connections and conceptual relationships.",
            inputSchema={
                "type": "object",
                "properties": {
                    "branch": {"type": "string", "description": "Optional: filter by branch"},
                    "link_type": {"type": "string", "description": "Optional: filter by type (resonance, causal, contradiction, elaboration, application)"}
                }
            }
        ),
        Tool(
            name="boswell_graph",
            description="Get full memory graph—nodes and edges. Use for topology analysis or visualization.",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="boswell_reflect",
            description="Get AI-surfaced insights—highly connected memories and cross-branch patterns. Use for strategic review.",
            inputSchema={"type": "object", "properties": {}}
        ),

        # WRITE OPERATIONS
        Tool(
            name="boswell_commit",
            description="Preserve a decision, insight, or context to memory. ALWAYS capture WHY, not just WHAT—future instances need reasoning. Call after completing steps, solving problems, making decisions, or learning something new. Use content_type='plan' to create persistent work plans that group tasks.",
            inputSchema={
                "type": "object",
                "properties": {
                    "branch": {"type": "string", "description": "Branch to commit to (tint-atlanta, iris, tint-empire, family, command-center, boswell)"},
                    "content": {"type": "object", "description": "Memory content as JSON object"},
                    "message": {"type": "string", "description": "Commit message describing the memory"},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "Optional tags for categorization"},
                    "force_branch": {"type": "boolean", "description": "Suppress routing warnings - use when intentionally committing to a branch despite mismatch"},
                    "content_type": {"type": "string", "description": "Content type: 'memory' (default) or 'skill' (behavioral instruction)"}
                },
                "required": ["branch", "content", "message"]
            }
        ),
        Tool(
            name="boswell_link",
            description="Create a resonance link between two memories. Captures conceptual connections across branches. Explain the reasoning—links are for pattern discovery.",
            inputSchema={
                "type": "object",
                "properties": {
                    "source_blob": {"type": "string", "description": "Source memory blob hash"},
                    "target_blob": {"type": "string", "description": "Target memory blob hash"},
                    "source_branch": {"type": "string", "description": "Source branch name"},
                    "target_branch": {"type": "string", "description": "Target branch name"},
                    "link_type": {"type": "string", "description": "Type: resonance, causal, contradiction, elaboration, application", "default": "resonance"},
                    "reasoning": {"type": "string", "description": "Why these memories are connected"}
                },
                "required": ["source_blob", "target_blob", "source_branch", "target_branch", "reasoning"]
            }
        ),
        Tool(
            name="boswell_checkout",
            description="Switch focus to a different branch. Use when changing work contexts.",
            inputSchema={
                "type": "object",
                "properties": {
                    "branch": {"type": "string", "description": "Branch to check out"}
                },
                "required": ["branch"]
            }
        ),

        # TASK QUEUE
        Tool(
            name="boswell_create_task",
            description="Add a task to the queue for yourself or other agents. Use to spawn subtasks, track work, or hand off to other instances.",
            inputSchema={
                "type": "object",
                "properties": {
                    "description": {"type": "string", "description": "What needs to be done"},
                    "title": {"type": "string", "description": "Short display name for the work item"},
                    "branch": {"type": "string", "description": "Which branch this relates to"},
                    "priority": {"type": "integer", "description": "Priority 1-10 (1=highest, default=5)"},
                    "assigned_to": {"type": "string", "description": "Optional: assign to specific instance"},
                    "metadata": {"type": "object", "description": "Optional: additional context"},
                    "plan_blob_hash": {"type": "string", "description": "Blob hash of the plan this task serves"}
                },
                "required": ["description"]
            }
        ),
        Tool(
            name="boswell_claim_task",
            description="Claim a task to prevent other agents from working on it. Call when starting work from the queue. Always provide your instance_id.",
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
            description="Release a claimed task. Use 'completed' when done, 'blocked' if stuck, 'manual' to just unclaim. Always release what you claim.",
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
            description="Update task status, description, or priority. Use to report progress or modify details.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID to update"},
                    "status": {"type": "string", "enum": ["open", "claimed", "blocked", "done"], "description": "New status"},
                    "title": {"type": "string", "description": "Short display name for the task"},
                    "description": {"type": "string", "description": "Updated description"},
                    "priority": {"type": "integer", "description": "Priority (1=highest)"},
                    "metadata": {"type": "object", "description": "Additional metadata to merge"},
                    "plan_blob_hash": {"type": "string", "description": "Blob hash of the plan this task serves"}
                },
                "required": ["task_id"]
            }
        ),
        Tool(
            name="boswell_delete_task",
            description="Soft-delete a task. Use for cleanup after completion or cancellation.",
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
            description="EMERGENCY STOP. Halts all task processing, blocks claims. Use when swarm behavior is problematic or coordination breaks down.",
            inputSchema={
                "type": "object",
                "properties": {
                    "reason": {"type": "string", "description": "Why halting (default: 'Manual emergency halt')"}
                }
            }
        ),
        Tool(
            name="boswell_resume_tasks",
            description="Resume task processing after a halt. Clears the halt flag.",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="boswell_halt_status",
            description="Check if task system is halted. Call before claiming tasks if unsure.",
            inputSchema={"type": "object", "properties": {}}
        ),

        # TRAILS
        Tool(
            name="boswell_record_trail",
            description="Record a traversal between memories. Strengthens the path for future recall. Trails that aren't traversed decay over time.",
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
            description="Get strongest memory trails—frequently traversed paths. Shows what's top of mind.",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Max trails to return (default: 20)"}
                }
            }
        ),
        Tool(
            name="boswell_trails_from",
            description="Get outbound trails from a memory. Shows what's typically accessed next.",
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
            description="Get inbound trails to a memory. Shows what typically leads here.",
            inputSchema={
                "type": "object",
                "properties": {
                    "blob": {"type": "string", "description": "Target memory blob hash"}
                },
                "required": ["blob"]
            }
        ),
        Tool(
            name="boswell_trail_health",
            description="Trail system health—state distribution (ACTIVE/FADING/DORMANT/ARCHIVED), activity metrics. Use to monitor memory decay.",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="boswell_buried_memories",
            description="Find dormant and archived trails—memory paths fading from recall. These can be resurrected by traversing them.",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Max trails to return (default: 20)"},
                    "include_archived": {"type": "boolean", "description": "Include archived trails (default: true)"}
                }
            }
        ),
        Tool(
            name="boswell_decay_forecast",
            description="Predict when trails will decay. Use to identify memories at risk of fading.",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="boswell_resurrect",
            description="Resurrect a dormant trail by traversing it. Doubles strength, resets to ACTIVE. Use to save important paths from decay.",
            inputSchema={
                "type": "object",
                "properties": {
                    "trail_id": {"type": "string", "description": "Trail ID to resurrect"},
                    "source_blob": {"type": "string", "description": "Or: source blob hash"},
                    "target_blob": {"type": "string", "description": "Or: target blob hash"}
                }
            }
        ),

        # HIPPOCAMPAL (Working Memory)
        Tool(
            name="boswell_bookmark",
            description="Lightweight memory staging. Use for observations, patterns, context that MIGHT be worth remembering. Cheaper than commit—expires in 7 days unless replayed. Default salience 0.3.",
            inputSchema={
                "type": "object",
                "properties": {
                    "branch": {"type": "string", "description": "Branch to stage on"},
                    "summary": {"type": "string", "description": "Brief summary of the observation/insight"},
                    "content": {"type": "object", "description": "Optional structured content"},
                    "context": {"type": "string", "description": "Optional working context description—used for auto-replay differentiation"},
                    "message": {"type": "string", "description": "Optional commit-style message"},
                    "salience": {"type": "number", "description": "Importance 0-1 (default 0.3). Higher = more likely to be promoted"},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "Optional tags"},
                    "source_instance": {"type": "string", "description": "Which instance created this (e.g., CC1, CW-PM)"},
                    "ttl_days": {"type": "integer", "description": "Days until expiry (default 7)"}
                },
                "required": ["branch", "summary"]
            }
        ),
        Tool(
            name="boswell_replay",
            description="Record topic recurrence—strengthens a bookmark's case for permanent storage. Increases replay_count. Near-expiry bookmarks with 3+ replays get TTL extension.",
            inputSchema={
                "type": "object",
                "properties": {
                    "candidate_id": {"type": "string", "description": "UUID of the candidate to replay"},
                    "keywords": {"type": "string", "description": "Alternative: semantic search for matching candidate"},
                    "replay_context": {"type": "string", "description": "Optional context of the replay"},
                    "session_id": {"type": "string", "description": "Optional session identifier"}
                }
            }
        ),
        Tool(
            name="boswell_consolidate",
            description="Manual consolidation trigger—score and promote top candidates to permanent memory. Use dry_run=true to preview scores without committing.",
            inputSchema={
                "type": "object",
                "properties": {
                    "branch": {"type": "string", "description": "Optional: only consolidate this branch"},
                    "dry_run": {"type": "boolean", "description": "Preview scores without promoting (default false)", "default": False},
                    "min_score": {"type": "number", "description": "Minimum consolidation score to promote (default 0)", "default": 0},
                    "max_promotions": {"type": "integer", "description": "Max candidates to promote (default 10)", "default": 10}
                }
            }
        ),
        Tool(
            name="boswell_candidates",
            description="View staging buffer—what's in working memory. Shows bookmarks with salience, replay count, and expiry.",
            inputSchema={
                "type": "object",
                "properties": {
                    "branch": {"type": "string", "description": "Optional: filter by branch"},
                    "status": {"type": "string", "description": "Optional: filter by status (active, cooling, promoted, expired)"},
                    "sort": {"type": "string", "description": "Sort by: salience, replay_count, created_at, expires_at (default created_at)"},
                    "limit": {"type": "integer", "description": "Max results (default 20)", "default": 20}
                }
            }
        ),
        Tool(
            name="boswell_decay_status",
            description="View expiring candidates—what's about to be forgotten. Shows bookmarks expiring within N days.",
            inputSchema={
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "Show candidates expiring within this many days (default 2)", "default": 2}
                }
            }
        ),

        # IMMUNE SYSTEM
        Tool(
            name="boswell_quarantine_list",
            description="List all quarantined memories awaiting human review. Quarantined memories are anomalies detected by the immune system patrol.",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "Max entries to return (default: 50)", "default": 50}
                }
            }
        ),
        Tool(
            name="boswell_quarantine_resolve",
            description="Resolve a quarantined memory: reinstate it to active status or permanently delete it. Always provide a reason.",
            inputSchema={
                "type": "object",
                "properties": {
                    "blob_hash": {"type": "string", "description": "Hash of the quarantined blob"},
                    "action": {"type": "string", "enum": ["reinstate", "delete"], "description": "Whether to reinstate or delete"},
                    "reason": {"type": "string", "description": "Why you're reinstating or deleting this memory"}
                },
                "required": ["blob_hash", "action"]
            }
        ),
        Tool(
            name="boswell_immune_status",
            description="Get immune system health: quarantine counts, last patrol time, branch health scores. Use to monitor memory graph health.",
            inputSchema={"type": "object", "properties": {}}
        ),

        # SESSION & ROUTING
        Tool(
            name="boswell_checkpoint",
            description="Save session checkpoint for crash recovery. Captures WHERE you are—progress, next step, context.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID to checkpoint"},
                    "instance_id": {"type": "string", "description": "Your instance identifier"},
                    "progress": {"type": "string", "description": "Human-readable progress description"},
                    "next_step": {"type": "string", "description": "What to do next on resume"},
                    "context_snapshot": {"type": "object", "description": "Arbitrary context data to preserve"}
                },
                "required": ["task_id"]
            }
        ),
        Tool(
            name="boswell_resume",
            description="Get checkpoint for a task. Use to resume after crash or context loss.",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID to resume"}
                },
                "required": ["task_id"]
            }
        ),
        Tool(
            name="boswell_validate_routing",
            description="Check which branch best matches content before committing. Returns confidence scores. Use when unsure about branch selection.",
            inputSchema={
                "type": "object",
                "properties": {
                    "content": {"type": "object", "description": "Content to analyze"},
                    "branch": {"type": "string", "description": "Requested branch"}
                },
                "required": ["content"]
            }
        ),

        # LANDSCAPE
        Tool(
            name="boswell_landscape",
            description="View the full work landscape—branches as projects, plans with progress, cascade health scores, and unorganized backlog. Call when you need the big picture.",
            inputSchema={
                "type": "object",
                "properties": {
                    "branch": {"type": "string", "description": "Optional: filter by branch"},
                    "include_done": {"type": "boolean", "description": "Include completed plans (default: false)"}
                }
            }
        ),
    ]


# ==================== TOOL HANDLERS ====================

@app.call_tool()
async def call_tool(name: str, arguments: dict):
    """Handle tool calls by proxying to Boswell API."""
    log(f"TOOL: {name}")
    headers = _build_headers()

    async with httpx.AsyncClient(timeout=30.0, headers=headers) as client:
        try:
            resp = await _dispatch_tool(client, name, arguments)
            if resp is None:
                return [TextContent(type="text", text=f"Unknown tool: {name}")]

            # If dispatch returned TextContent directly, pass through
            if isinstance(resp, list):
                return resp

            # Format response
            if resp.status_code in (200, 201):
                try:
                    data = resp.json()
                    return [TextContent(type="text", text=json.dumps(data, indent=2))]
                except Exception:
                    return [TextContent(type="text", text=resp.text)]
            else:
                return [TextContent(type="text", text=f"Error {resp.status_code}: {resp.text}")]

        except httpx.TimeoutException:
            return [TextContent(type="text", text="Error: Request to Boswell API timed out")]
        except Exception as e:
            log(f"ERROR: {name}: {e}")
            return [TextContent(type="text", text=f"Error: {e}")]


async def _dispatch_tool(client: httpx.AsyncClient, name: str, args: dict):
    """Dispatch a tool call to the appropriate API endpoint."""
    api = BOSWELL_API

    # ── STARTUP / READ ──
    if name == "boswell_startup":
        params = {
            "context": args.get("context", "important decisions and active commitments"),
            "k": args.get("k", 5),
            "verbosity": args.get("verbosity", "normal"),
        }
        resp = await client.get(f"{api}/startup", params=params)
        return [TextContent(type="text", text=json.dumps(resp.json(), indent=2))] if resp.status_code == 200 else resp

    if name == "boswell_brief":
        return await client.get(f"{api}/quick-brief", params={"branch": args.get("branch", "command-center")})

    if name == "boswell_branches":
        return await client.get(f"{api}/branches")

    if name == "boswell_head":
        return await client.get(f"{api}/head", params={"branch": args["branch"]})

    if name == "boswell_log":
        params = {"branch": args["branch"]}
        if "limit" in args:
            params["limit"] = args["limit"]
        return await client.get(f"{api}/log", params=params)

    if name == "boswell_search":
        params = {"q": args["query"]}
        if "branch" in args:
            params["branch"] = args["branch"]
        if "limit" in args:
            params["limit"] = args["limit"]
        return await client.get(f"{api}/search", params=params)

    if name == "boswell_semantic_search":
        params = {"q": args["query"]}
        if "limit" in args:
            params["limit"] = args["limit"]
        return await client.get(f"{api}/semantic-search", params=params)

    if name == "boswell_recall":
        params = {}
        if "hash" in args:
            params["hash"] = args["hash"]
        if "commit" in args:
            params["commit"] = args["commit"]
        return await client.get(f"{api}/recall", params=params)

    if name == "boswell_links":
        params = {}
        if "branch" in args:
            params["branch"] = args["branch"]
        if "link_type" in args:
            params["link_type"] = args["link_type"]
        return await client.get(f"{api}/links", params=params)

    if name == "boswell_graph":
        return await client.get(f"{api}/graph")

    if name == "boswell_reflect":
        return await client.get(f"{api}/reflect")

    # ── WRITE ──
    if name == "boswell_commit":
        payload = {
            "branch": args["branch"],
            "content": args["content"],
            "message": args["message"],
            "author": "claude-code",
            "type": args.get("content_type", "memory"),
        }
        if "tags" in args:
            payload["tags"] = args["tags"]
        if args.get("force_branch"):
            payload["force_branch"] = True
        resp = await client.post(f"{api}/commit", json=payload)
        # Surface routing warnings
        if resp.status_code in (200, 201):
            data = resp.json()
            if "routing_suggestion" in data:
                rs = data["routing_suggestion"]
                warning = f"\n\nROUTING WARNING: {rs['message']}\nAdd force_branch=true to suppress."
                return [TextContent(type="text", text=json.dumps(data, indent=2) + warning)]
        return resp

    if name == "boswell_link":
        payload = {
            "source_blob": args["source_blob"],
            "target_blob": args["target_blob"],
            "source_branch": args["source_branch"],
            "target_branch": args["target_branch"],
            "link_type": args.get("link_type", "resonance"),
            "reasoning": args["reasoning"],
            "created_by": "claude-code",
        }
        return await client.post(f"{api}/link", json=payload)

    if name == "boswell_checkout":
        return await client.post(f"{api}/checkout", json={"branch": args["branch"]})

    # ── TASKS ──
    if name == "boswell_create_task":
        payload = {"description": args["description"]}
        for field in ("title", "branch", "priority", "assigned_to", "metadata", "plan_blob_hash"):
            if field in args:
                payload[field] = args[field]
        return await client.post(f"{api}/tasks", json=payload)

    if name == "boswell_claim_task":
        return await client.post(f"{api}/tasks/{args['task_id']}/claim", json={"instance_id": args["instance_id"]})

    if name == "boswell_release_task":
        return await client.post(
            f"{api}/tasks/{args['task_id']}/release",
            json={"instance_id": args["instance_id"], "reason": args.get("reason", "manual")},
        )

    if name == "boswell_update_task":
        payload = {}
        for field in ("status", "title", "description", "priority", "metadata", "plan_blob_hash"):
            if field in args:
                payload[field] = args[field]
        return await client.patch(f"{api}/tasks/{args['task_id']}", json=payload)

    if name == "boswell_delete_task":
        return await client.delete(f"{api}/tasks/{args['task_id']}")

    if name == "boswell_halt_tasks":
        payload = {}
        if "reason" in args:
            payload["reason"] = args["reason"]
        return await client.post(f"{api}/tasks/halt", json=payload)

    if name == "boswell_resume_tasks":
        return await client.post(f"{api}/tasks/resume", json={})

    if name == "boswell_halt_status":
        return await client.get(f"{api}/tasks/halt-status")

    # ── TRAILS ──
    if name == "boswell_record_trail":
        return await client.post(f"{api}/trails/record", json={"source_blob": args["source_blob"], "target_blob": args["target_blob"]})

    if name == "boswell_hot_trails":
        params = {}
        if "limit" in args:
            params["limit"] = args["limit"]
        return await client.get(f"{api}/trails/hot", params=params)

    if name == "boswell_trails_from":
        return await client.get(f"{api}/trails/from/{args['blob']}")

    if name == "boswell_trails_to":
        return await client.get(f"{api}/trails/to/{args['blob']}")

    if name == "boswell_trail_health":
        return await client.get(f"{api}/trails/health")

    if name == "boswell_buried_memories":
        params = {}
        if "limit" in args:
            params["limit"] = args["limit"]
        if "include_archived" in args:
            params["include_archived"] = args["include_archived"]
        return await client.get(f"{api}/trails/buried", params=params)

    if name == "boswell_decay_forecast":
        return await client.get(f"{api}/trails/decay-forecast")

    if name == "boswell_resurrect":
        payload = {}
        for field in ("trail_id", "source_blob", "target_blob"):
            if field in args:
                payload[field] = args[field]
        return await client.post(f"{api}/trails/resurrect", json=payload)

    # ── HIPPOCAMPAL ──
    if name == "boswell_bookmark":
        payload = {"branch": args["branch"], "summary": args["summary"]}
        for field in ("content", "context", "message", "salience", "tags", "source_instance", "ttl_days"):
            if field in args:
                payload[field] = args[field]
        return await client.post(f"{api}/bookmark", json=payload)

    if name == "boswell_replay":
        payload = {}
        for field in ("candidate_id", "keywords", "replay_context", "session_id"):
            if field in args:
                payload[field] = args[field]
        return await client.post(f"{api}/replay", json=payload)

    if name == "boswell_consolidate":
        payload = {}
        for field in ("branch", "dry_run", "min_score", "max_promotions"):
            if field in args:
                payload[field] = args[field]
        return await client.post(f"{api}/consolidate", json=payload)

    if name == "boswell_candidates":
        params = {}
        for field in ("branch", "status", "sort", "limit"):
            if field in args:
                params[field] = args[field]
        return await client.get(f"{api}/candidates", params=params)

    if name == "boswell_decay_status":
        params = {}
        if "days" in args:
            params["days"] = args["days"]
        return await client.get(f"{api}/decay-status", params=params)

    # ── IMMUNE ──
    if name == "boswell_quarantine_list":
        params = {}
        if "limit" in args:
            params["limit"] = args["limit"]
        return await client.get(f"{api}/quarantine", params=params)

    if name == "boswell_quarantine_resolve":
        return await client.post(f"{api}/quarantine/resolve", json={
            "blob_hash": args["blob_hash"],
            "action": args["action"],
            "reason": args.get("reason", ""),
        })

    if name == "boswell_immune_status":
        return await client.get(f"{api}/immune/status")

    # ── SESSION ──
    if name == "boswell_checkpoint":
        payload = {"task_id": args["task_id"]}
        for field in ("instance_id", "progress", "next_step", "context_snapshot"):
            if field in args:
                payload[field] = args[field]
        return await client.post(f"{api}/session/checkpoint", json=payload)

    if name == "boswell_resume":
        return await client.get(f"{api}/session/checkpoint/{args['task_id']}")

    if name == "boswell_validate_routing":
        payload = {"content": args["content"]}
        if "branch" in args:
            payload["branch"] = args["branch"]
        return await client.post(f"{api}/validate-routing", json=payload)

    # ── LANDSCAPE ──
    if name == "boswell_landscape":
        params = {}
        if "branch" in args:
            params["branch"] = args["branch"]
        if "include_done" in args:
            params["include_done"] = args["include_done"]
        return await client.get(f"{api}/landscape", params=params)

    return None  # Unknown tool


# ==================== MAIN ====================

async def main():
    """Run the MCP server via stdio."""
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
