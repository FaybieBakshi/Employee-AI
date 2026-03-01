# Cross-Domain Orchestration Skill

Handle tasks that span multiple domains: email + accounting, WhatsApp +
social, Gmail + Odoo, etc. Coordinate all AI Employee systems together.

## When to Use

- Task involves two or more of: email, accounting, social media, WhatsApp
- User wants the full AI Employee pipeline from intake to completion
- End-to-end automation: detect → process → act → log → report
- User asks "run everything" or "process all pending items"

## Cross-Domain Workflows

### Email → Invoice Flow
```
1. Gmail Watcher detects "invoice request" email
2. Creates EMAIL_<id>.md in Needs_Action/
3. /vault-manager processes it:
   a. Reads email content
   b. Calls odoo MCP: create_draft_invoice
   c. Creates APPROVAL_invoice_<date>.md in Pending_Approval/
4. Human approves → Approval Watcher posts to Odoo
5. Confirmation email drafted via email MCP
```

### WhatsApp → Social Flow
```
1. WhatsApp Watcher detects "urgent" or "announcement"
2. Creates WHATSAPP_<ts>.md in Needs_Action/
3. /vault-manager processes it:
   a. Drafts social post from message content
   b. Creates APPROVAL_facebook_<date>.md in Pending_Approval/
4. Human approves → Approval Watcher posts to Facebook/Instagram
```

### Weekly Full Pipeline
```
1. Scheduler triggers Monday at 08:00
2. ralph_wiggum.py --batch runs full Needs_Action queue
3. audit.weekly_audit generates CEO Briefing
4. Briefing saved to /Briefings/
5. Optional: briefing emailed via email MCP
```

## Running Everything

```bash
# Start all watchers + scheduler (full Gold Tier)
python orchestrator.py --watchers fs,gmail,approval,whatsapp

# Process queue with persistence loop
python ralph_wiggum.py --batch

# Generate weekly report
python -m audit.weekly_audit
```

## System Architecture

```
Watchers              →  Needs_Action/  →  Claude Code  →  Actions
─────────────────────────────────────────────────────────────────────
FilesystemWatcher     →  FILE_*         →  vault-manager →  Plans/
GmailWatcher          →  EMAIL_*        →  reasoning-loop →  Done/
ApprovalWatcher       →  APPROVAL_*     →  hitl-workflow  →  Approved/
WhatsAppWatcher       →  WHATSAPP_*     →  cross-domain   →  Social/

MCP Servers           →  Tools          →  HITL Gate
─────────────────────────────────────────────────────────────────────
email_mcp             →  send_email     →  Pending_Approval/
odoo_mcp              →  invoices       →  Pending_Approval/
social_mcp            →  posts          →  Pending_Approval/

Audit & Recovery
─────────────────────────────────────────────────────────────────────
audit_logger          →  Logs/*.json    →  weekly_audit  →  Briefings/
retry_handler         →  CircuitBreaker →  safe_call wrapper
stop_hook             →  Ralph Wiggum   →  persistence loop
```

## Error Recovery

All cross-domain calls use the circuit breaker pattern:

```python
from recovery.retry_handler import safe_call, get_circuit

result = safe_call(
    external_api_function,
    arg1, arg2,
    fallback={"queued": True},
    circuit_breaker=get_circuit("gmail"),
    max_attempts=3,
)
```

If a service goes down, the circuit opens and falls back gracefully.
The circuit resets automatically after the configured timeout.

## Audit Trail

Every cross-domain action is logged:
- `Logs/YYYY-MM-DD.json` — structured JSON per action
- `Plans/Plan_*.md` — decision log per task
- `Done/*.md` — completed task archive
- `Briefings/*_Weekly_CEO_Briefing.md` — weekly summary
