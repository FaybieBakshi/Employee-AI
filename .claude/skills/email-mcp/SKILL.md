---
name: email-mcp
description: |
  Use the Email MCP server to send emails or create email drafts. The server
  exposes send_email and draft_email tools. Always use draft_email first —
  send_email should only be called after human approval per Handbook §3.
---

# Email MCP

Send and draft emails via the built-in SMTP MCP server.

## Available Tools

| Tool | Safe to auto-call? | Description |
|------|--------------------|-------------|
| `draft_email` | ✅ Yes | Saves draft to `/Pending_Approval` — does NOT send |
| `send_email` | ❌ No (approval required) | Sends via SMTP — only after human approves |

## Setup

### 1. Configure SMTP in .env

For Gmail (recommended):
```
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your.email@gmail.com
SMTP_PASSWORD=abcd efgh ijkl mnop   # App Password (NOT your main password)
```

To get a Gmail App Password:
1. Enable 2-Factor Authentication at myaccount.google.com
2. Go to myaccount.google.com/apppasswords
3. Generate a new app password for "Mail"
4. Paste (without spaces) into `SMTP_PASSWORD`

### 2. Register with Claude Code (already done via .mcp.json)

The server is pre-configured in `.mcp.json`. Claude Code loads it automatically.

To verify:
```bash
claude mcp list
```
Should show `email` server.

### 3. Test the server manually
```bash
echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","clientInfo":{"name":"test","version":"1.0"},"capabilities":{}}}' \
  | python -m mcp_servers.email_mcp
```

## Usage in Claude Code

### Draft an email (safe — requires approval to send)
```
Use the draft_email tool:
  to: "client@example.com"
  subject: "Re: Project Update"
  body: "Dear [Name],\n\nThank you for your message..."
  reason: "Reply to client inquiry about project status"
```

Claude will call the `draft_email` MCP tool, which saves the draft to
`AI_Employee_Vault/Pending_Approval/APPROVAL_email_<date>.md`.

### After human approval — send the email
Once the human moves the draft to `/Approved`, the Approval Watcher executes
the send automatically. Alternatively, Claude can call `send_email` directly
only after the human has confirmed approval in conversation.

## Dry Run Mode

Set `DRY_RUN=true` in `.env` (the default). In dry run mode:
- `send_email` logs the action but does not connect to SMTP
- `draft_email` still writes the file (always safe)

Switch to `DRY_RUN=false` when ready for production.

## MCP Server Config (.mcp.json)

```json
{
  "mcpServers": {
    "email": {
      "command": "python3",
      "args": ["-m", "mcp_servers.email_mcp"],
      "env": {
        "VAULT_PATH": "AI_Employee_Vault",
        "DRY_RUN": "true"
      }
    }
  }
}
```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `SMTP_USER not configured` | Add `SMTP_USER` and `SMTP_PASSWORD` to `.env` |
| `535 Authentication failed` | Use an App Password, not your main password |
| `Connection refused` | Check `SMTP_HOST` and `SMTP_PORT` in `.env` |
| MCP server not found | Run `claude mcp list` to verify registration |
| Draft not appearing | Check `AI_Employee_Vault/Pending_Approval/` folder |
