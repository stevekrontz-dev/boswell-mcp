#!/usr/bin/env python3
"""Phase 5: Add routing warning to boswell_commit in MCP server"""

with open('server.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find the boswell_commit handler and modify it
new_lines = []
i = 0
while i < len(lines):
    line = lines[i]
    new_lines.append(line)
    
    # After 'if "tags" in arguments:' and its following line, add force_branch
    if 'if "tags" in arguments:' in line:
        i += 1
        new_lines.append(lines[i])  # payload["tags"] = arguments["tags"]
        # Add force_branch support
        new_lines.append('                if arguments.get("force_branch"):\n')
        new_lines.append('                    payload["force_branch"] = True\n')
    
    # After resp = await client.post(f"{BOSWELL_API}/commit", json=payload), add warning logic
    elif 'resp = await client.post(f"{BOSWELL_API}/commit", json=payload)' in line:
        # Add routing warning logic
        new_lines.append('\n')
        new_lines.append('                # Phase 5: Surface routing warnings\n')
        new_lines.append('                if resp.status_code in (200, 201):\n')
        new_lines.append('                    data = resp.json()\n')
        new_lines.append('                    if "routing_suggestion" in data:\n')
        new_lines.append('                        rs = data["routing_suggestion"]\n')
        new_lines.append('                        warning = f"\\n\\nROUTING WARNING: {rs[\'message\']}\\nAdd force_branch=true to suppress."\n')
        new_lines.append('                        return [TextContent(type="text", text=json.dumps(data, indent=2) + warning)]\n')
    
    i += 1

with open('server.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print('Added routing warning to boswell_commit')
