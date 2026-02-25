"""Boswell CLI - Setup and serve commands.

Usage:
    boswell init     - Interactive setup wizard
    boswell serve    - Start MCP stdio server
    boswell status   - Check connection status
"""

import argparse
import getpass
import json
import os
import sys

import httpx

from . import __version__
from .config import (
    DEFAULT_API_URL,
    DEFAULT_BRANCHES,
    add_mcp_entry,
    detect_claude_code,
    generate_config_summary,
    write_claude_md_instructions,
)


def print_banner():
    print(f"""
╔══════════════════════════════════════╗
║       Boswell Memory System          ║
║       v{__version__:<30s}║
║       Persistent memory for Claude   ║
╚══════════════════════════════════════╝
""")


def cmd_init(args):
    """Interactive setup wizard."""
    print_banner()

    api_url = args.api_url or DEFAULT_API_URL
    api_key = args.api_key

    # Step 1: Account
    if not api_key:
        print("Step 1: Account Setup")
        print("─" * 40)
        has_account = input("Do you have a Boswell account? [y/N]: ").strip().lower()

        if has_account in ("y", "yes"):
            api_key = input("Enter your API key (bos_...): ").strip()
            if not api_key.startswith("bos_"):
                print("Warning: API keys typically start with 'bos_'")
        else:
            print("\nCreating a new account...")
            email = input("Email: ").strip()
            password = getpass.getpass("Password: ")
            password_confirm = getpass.getpass("Confirm password: ")

            if password != password_confirm:
                print("Error: Passwords don't match.")
                sys.exit(1)

            print(f"\nRegistering with {api_url.replace('/v2', '')}/v2/onboard/provision...")
            try:
                resp = httpx.post(
                    f"{api_url}/onboard/provision",
                    json={"email": email, "password": password},
                    timeout=30.0,
                )
                if resp.status_code in (200, 201):
                    data = resp.json()
                    api_key = data["api_key"]
                    print(f"Account created! Your API key: {api_key}")
                    print("SAVE THIS KEY - you won't see it again.")
                else:
                    print(f"Error: {resp.status_code} - {resp.text}")
                    sys.exit(1)
            except httpx.ConnectError:
                print(f"Error: Could not connect to {api_url}")
                sys.exit(1)

    # Step 2: Claude Code detection
    print("\nStep 2: Claude Code Integration")
    print("─" * 40)

    if detect_claude_code():
        print("Claude Code detected!")
        added = add_mcp_entry(api_key, api_url)
        if added:
            print("MCP config written to ~/.claude.json")
        else:
            print("Boswell already configured in ~/.claude.json (skipped)")
    else:
        print("Claude Code not found on PATH.")
        print("Manual config for ~/.claude.json:")
        manual_config = {
            "mcpServers": {
                "boswell": {
                    "type": "stdio",
                    "command": "boswell",
                    "args": ["serve"],
                    "env": {
                        "BOSWELL_API_KEY": api_key,
                        "BOSWELL_API": api_url,
                    }
                }
            }
        }
        print(json.dumps(manual_config, indent=2))

    # Step 3: CLAUDE.md instructions
    print("\nStep 3: Startup Instructions")
    print("─" * 40)

    # Branch customization
    print(f"Default branches: {', '.join(DEFAULT_BRANCHES)}")
    custom = input("Customize branches? [y/N]: ").strip().lower()
    branches = DEFAULT_BRANCHES
    if custom in ("y", "yes"):
        branch_input = input("Enter branch names (comma-separated): ").strip()
        branches = [b.strip() for b in branch_input.split(",") if b.strip()]
        if not branches:
            branches = DEFAULT_BRANCHES

    written = write_claude_md_instructions(branches)
    if written:
        print("Boswell instructions written to ~/.claude/CLAUDE.md")
    else:
        print("Boswell instructions already in CLAUDE.md (skipped)")

    # Step 4: Seed sacred manifest
    print("\nStep 4: Sacred Manifest")
    print("─" * 40)
    seed = input("Seed a starter sacred manifest? [Y/n]: ").strip().lower()
    if seed not in ("n", "no"):
        try:
            resp = httpx.post(
                f"{api_url}/onboard/seed-manifest",
                headers={"X-API-Key": api_key},
                json={"branches": branches},
                timeout=30.0,
            )
            if resp.status_code in (200, 201):
                print("Sacred manifest seeded!")
            else:
                print(f"Warning: Could not seed manifest ({resp.status_code})")
        except Exception as e:
            print(f"Warning: Could not seed manifest ({e})")

    # Step 5: Test connection
    print("\nStep 5: Connection Test")
    print("─" * 40)
    try:
        resp = httpx.get(
            f"{api_url}/startup",
            headers={"X-API-Key": api_key},
            params={"context": "initial setup", "k": 1, "verbosity": "minimal"},
            timeout=15.0,
        )
        if resp.status_code == 200:
            print("Connection successful! Boswell is ready.")
        else:
            print(f"Warning: Got status {resp.status_code} from startup endpoint")
    except Exception as e:
        print(f"Warning: Connection test failed ({e})")

    # Summary
    print("\n" + "═" * 40)
    print(generate_config_summary(api_key, api_url))
    print("Setup complete! Open Claude Code and say:")
    print('  "Call boswell_startup"')
    print("═" * 40)


def cmd_serve(args):
    """Start the MCP stdio server."""
    # Import and run the server
    from .server import main
    import asyncio
    asyncio.run(main())


def cmd_status(args):
    """Check connection status."""
    api_url = os.environ.get("BOSWELL_API", DEFAULT_API_URL)
    api_key = os.environ.get("BOSWELL_API_KEY", "")
    internal_secret = os.environ.get("INTERNAL_SECRET", "")

    print(f"API URL: {api_url}")
    print(f"API Key: {'set' if api_key else 'not set'}")
    print(f"Internal Secret: {'set' if internal_secret else 'not set'}")

    headers = {}
    if api_key:
        headers["X-API-Key"] = api_key
    elif internal_secret:
        headers["X-Boswell-Internal"] = internal_secret

    try:
        resp = httpx.get(f"{api_url}/health", headers=headers, timeout=10.0)
        print(f"Health check: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            print(f"  Status: {data.get('status', 'unknown')}")
    except Exception as e:
        print(f"Connection failed: {e}")


def main():
    parser = argparse.ArgumentParser(
        prog="boswell",
        description="Boswell Memory System - Persistent memory for Claude",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # init
    init_parser = subparsers.add_parser("init", help="Interactive setup wizard")
    init_parser.add_argument("--api-key", help="Pre-provide API key (skip account step)")
    init_parser.add_argument("--api-url", help=f"API URL (default: {DEFAULT_API_URL})")
    init_parser.set_defaults(func=cmd_init)

    # serve
    serve_parser = subparsers.add_parser("serve", help="Start MCP stdio server")
    serve_parser.set_defaults(func=cmd_serve)

    # status
    status_parser = subparsers.add_parser("status", help="Check connection status")
    status_parser.set_defaults(func=cmd_status)

    args = parser.parse_args()
    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
