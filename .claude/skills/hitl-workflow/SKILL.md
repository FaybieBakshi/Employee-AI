---
name: hitl-workflow
description: |
  Human-in-the-Loop (HITL) approval workflow. Use when you need to create an
  approval request for a sensitive action (email, payment, social post), check
  what is pending approval, or explain how the approval system works.
---

# HITL Workflow

Approval-first system for sensitive actions. No sensitive action executes without human sign-off.

## Core Rule (from Handbook §3)

| Action | Threshold |
|--------|-----------|
| Read vault files | Auto-approved |
| Write Plan/Dashboard files | Auto-approved |
| Move files to Done | Auto-approved |
| Send emails | **Requires approval** |
| Make payments | **Always requires approval** |
| Post to social media | **Requires approval** |
| Delete files | **Requires approval** |

## Creating an Approval Request

When a sensitive action is needed, write to `AI_Employee_Vault/Pending_Approval/`:

### Email approval file
```markdown
---
type: approval_request
action: send_email
to: "recipient@example.com"
subject: "Email subject here"
created: 2026-02-28T10:00:00Z
expires: 2026-03-01T10:00:00Z
status: pending
---

## Action Requested

Send email to recipient@example.com regarding: [reason]

### Email Body

[full email body here]

## To Approve
Move this file to `AI_Employee_Vault/Approved/`

## To Reject
Move this file to `AI_Employee_Vault/Rejected/`
```

### LinkedIn post approval file
```markdown
---
type: approval_request
action: post_linkedin
created: 2026-02-28T10:00:00Z
status: pending
---

## Post Content

[post text here]

## To Approve
Move to AI_Employee_Vault/Approved/

## To Reject
Move to AI_Employee_Vault/Rejected/
```

## Approval File Naming Convention (Handbook §5)

```
APPROVAL_<action>_<YYYY-MM-DD>.md
```

Examples:
- `APPROVAL_email_client_2026-02-28.md`
- `APPROVAL_linkedin_post_2026-02-28.md`
- `APPROVAL_payment_invoice_123_2026-02-28.md`

## Checking Pending Approvals

```bash
ls AI_Employee_Vault/Pending_Approval/
```

Or in Claude Code, use the Read tool to check each file.

## How the Approval Watcher Executes Actions

When a file is moved to `/Approved/`:

1. `approval_watcher.py` detects the file (watchdog event)
2. Reads the YAML frontmatter → gets `action` type
3. Dispatches the action:
   - `send_email` → SMTP via `SMTP_USER` / `SMTP_PASSWORD` in .env
   - `post_linkedin` → Playwright MCP client → LinkedIn Web
4. Logs result to `Logs/YYYY-MM-DD.json`
5. Moves file to `Done/`

## Running the Approval Watcher

```bash
# Start (monitors Pending_Approval/, Approved/, Rejected/)
python -m watchers.approval_watcher

# Dry run (logs actions but doesn't execute)
python -m watchers.approval_watcher --dry-run

# Via orchestrator (recommended — supervised, auto-restart)
python orchestrator.py
```

## Audit Trail

Every approval decision is logged to `Logs/YYYY-MM-DD.json`:

```json
{
  "timestamp": "2026-02-28T10:30:00Z",
  "action_type": "action_executed:send_email",
  "actor": "ApprovalWatcher",
  "target": "APPROVAL_email_client_2026-02-28.md",
  "result": "success",
  "details": {"result": "Email sent to client@example.com"}
}
```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Action watcher not running | Start via `python -m watchers.approval_watcher` or orchestrator |
| Email not sent after approval | Check `SMTP_USER` and `SMTP_PASSWORD` in .env |
| LinkedIn post failed | Ensure Playwright MCP is running and LinkedIn session is active |
| Approval file stuck in Done | Check Logs/ for error entries |
