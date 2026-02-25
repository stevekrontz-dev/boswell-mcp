"""Configuration detection and generation for Boswell MCP."""

import json
import os
import platform
import sys
from pathlib import Path


# Default API endpoint
DEFAULT_API_URL = "https://delightful-imagination-production-f6a1.up.railway.app/v2"

# Default branches for new users
DEFAULT_BRANCHES = ["command-center", "work", "personal", "research"]


def get_claude_config_dir() -> Path:
    """Get the .claude directory path (cross-platform)."""
    home = Path.home()
    return home / ".claude"


def get_claude_json_path() -> Path:
    """Get the path to ~/.claude.json (Claude Code MCP config)."""
    return Path.home() / ".claude.json"


def get_claude_md_path() -> Path:
    """Get the path to ~/.claude/CLAUDE.md."""
    return get_claude_config_dir() / "CLAUDE.md"


def detect_claude_code() -> bool:
    """Check if Claude Code CLI is installed."""
    # Check if 'claude' command exists on PATH
    from shutil import which
    return which("claude") is not None


def read_claude_json() -> dict:
    """Read existing ~/.claude.json or return empty dict."""
    path = get_claude_json_path()
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def write_claude_json(config: dict) -> None:
    """Write ~/.claude.json, preserving existing config."""
    path = get_claude_json_path()
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")


def add_mcp_entry(api_key: str, api_url: str = DEFAULT_API_URL) -> bool:
    """Add Boswell MCP server entry to ~/.claude.json.

    Returns True if entry was added, False if already exists.
    """
    config = read_claude_json()

    if "mcpServers" not in config:
        config["mcpServers"] = {}

    if "boswell" in config["mcpServers"]:
        return False  # Already configured

    config["mcpServers"]["boswell"] = {
        "type": "stdio",
        "command": "boswell",
        "args": ["serve"],
        "env": {
            "BOSWELL_API_KEY": api_key,
            "BOSWELL_API": api_url,
        }
    }

    write_claude_json(config)
    return True


def write_claude_md_instructions(branches: list[str] | None = None) -> bool:
    """Write Boswell startup instructions to ~/.claude/CLAUDE.md.

    Appends to existing file if present, or creates new one.
    Returns True if written, False if Boswell section already exists.
    """
    claude_dir = get_claude_config_dir()
    claude_dir.mkdir(parents=True, exist_ok=True)
    md_path = get_claude_md_path()

    # Check if Boswell instructions already exist
    if md_path.exists():
        existing = md_path.read_text(encoding="utf-8")
        if "boswell_startup" in existing.lower() or "# Boswell Memory System" in existing:
            return False  # Already has Boswell instructions

    # Load template
    template_path = Path(__file__).parent / "templates" / "claude_md.txt"
    template = template_path.read_text(encoding="utf-8")

    # Format branches
    branch_list = branches or DEFAULT_BRANCHES
    branch_lines = "\n".join(f"- **{b}**" for b in branch_list)
    content = template.replace("{branches}", branch_lines)

    # Append to existing or create new
    if md_path.exists():
        existing = md_path.read_text(encoding="utf-8")
        content = existing.rstrip() + "\n\n" + content

    md_path.write_text(content, encoding="utf-8")
    return True


def generate_config_summary(api_key: str, api_url: str = DEFAULT_API_URL) -> str:
    """Generate a summary of what was configured, for display to user."""
    return f"""
Boswell MCP Configuration:
  API URL:  {api_url}
  API Key:  {api_key[:8]}...{api_key[-4:]}

MCP Server Entry (in ~/.claude.json):
  Command:  boswell serve
  Auth:     BOSWELL_API_KEY environment variable

To verify: Open Claude Code and say "Call boswell_startup"
"""
