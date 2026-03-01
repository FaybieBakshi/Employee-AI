# WhatsApp Watcher Skill

Monitor WhatsApp Web for urgent messages using Playwright browser automation.
Detects keywords and creates Needs_Action items automatically.

## When to Use

- User wants to monitor WhatsApp for urgent business messages
- User asks to set up WhatsApp automation
- User wants to see what WhatsApp messages triggered actions

## Prerequisites

- Node.js installed (for Playwright)
- Playwright MCP server running
- WhatsApp account (phone with active WhatsApp)

## Quick Start

### 1. Install Playwright browsers (one-time)

```bash
pip install playwright
python -m playwright install chromium
```

### 2. First-time login (scan QR code)

```bash
python -m watchers.whatsapp_watcher --login
```

A browser window will open with WhatsApp Web. Scan the QR code with your phone.
The session is saved to `WHATSAPP_SESSION_PATH` (default: `.whatsapp_session/`).

### 3. Start the watcher

```bash
python -m watchers.whatsapp_watcher
```

Or include it in the orchestrator:

```bash
python orchestrator.py --watchers fs,approval,whatsapp
```

## Detected Keywords

The watcher flags messages containing:

| Category | Keywords |
|----------|----------|
| Urgent | urgent, URGENT, asap, ASAP |
| Financial | invoice, payment, invoice due, overdue |
| Business | meeting, contract, proposal |
| Alerts | error, failed, down, outage |

## Generated Action Files

When a keyword is detected, creates:
`AI_Employee_Vault/Needs_Action/WHATSAPP_<timestamp>_<contact>.md`

```yaml
---
type: whatsapp_message
contact: Contact Name
message_preview: First 200 chars of message...
keywords_detected: [urgent, invoice]
received_at: 2026-02-28T10:30:00Z
priority: high
---
```

## Environment Variables

```bash
WHATSAPP_SESSION_PATH=.whatsapp_session   # Where to store browser session
WHATSAPP_CHECK_INTERVAL=300               # Seconds between checks (default: 300)
VAULT_PATH=AI_Employee_Vault              # Vault location
```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| QR code expired | Run `--login` again |
| Session invalid | Delete `.whatsapp_session/` and re-login |
| Playwright not found | `pip install playwright && python -m playwright install chromium` |
| MCP server not running | Start with `npx @playwright/mcp@latest` |
