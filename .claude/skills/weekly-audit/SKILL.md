# Weekly Audit Skill

Generate a comprehensive weekly CEO briefing from all system data:
accounting (Odoo), completed tasks, social media, and AI activity logs.

## When to Use

- User asks for a weekly summary or CEO briefing
- Monday morning automated briefing is due
- User wants to review what happened last week
- User wants accounting + activity + social in one report

## Quick Start

```bash
# Generate briefing now
python -m audit.weekly_audit

# With custom vault path
python -m audit.weekly_audit --vault /path/to/vault
```

The briefing is saved to:
`AI_Employee_Vault/Briefings/YYYY-MM-DD_Weekly_CEO_Briefing.md`

## What's Included

| Section | Source | Requires |
|---------|--------|----------|
| Executive Summary | Vault folder counts | Always available |
| Accounting | Odoo API | ODOO_* credentials |
| Completed Tasks | /Done/ (last 7 days) | Always available |
| Social Engagement | /Social/ .md files | Social watchers running |
| AI Activity | /Logs/ JSON files | Audit logger running |
| Subscription Audit | /Accounting/ .md files | Manual accounting entries |
| Action Required | /Pending_Approval/ | Always available |

## Scheduling

The briefing runs automatically every **Monday at 08:00** via scheduler.py.
To override the day/time, set in `.env`:

```bash
CEO_BRIEFING_DAY=monday
WEEKLY_AUDIT_TIME=08:00
```

## Audit Logger

All AI actions are logged to `/Logs/YYYY-MM-DD.json`:

```python
from audit.audit_logger import get_logger
logger = get_logger()

# Log an action
logger.log_business("email_sent", "client@example.com", "success")
logger.log_error("api_call", "odoo", "timeout")

# Query logs
entries = logger.get_weekly_entries()
summary = logger.daily_summary()
```

Log files are retained for 90 days, then automatically deleted.

## Reading a Briefing

Briefings are plain Markdown files — open in Obsidian, any text editor, or:

```bash
cat AI_Employee_Vault/Briefings/2026-02-28_Weekly_CEO_Briefing.md
```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Odoo section shows "not available" | Configure ODOO_* in .env |
| No completed tasks listed | Check /Done/ folder has .md files modified in last 7 days |
| Social section empty | Run Facebook/Twitter watchers or social MCP first |
| Briefings/ folder missing | Created automatically on first run |
