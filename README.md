# Personal AI Employee — Gold Tier

> Hackathon 0: Building Autonomous FTEs in 2026

A fully-automated AI employee built with Claude Code, running three tiers of capability:
**Bronze** (vault + file watcher) → **Silver** (email + LinkedIn + HITL) → **Gold** (WhatsApp + social + accounting + persistence loop).

---

## Architecture

```
Watchers                 Vault (Obsidian)         Claude Code
────────────────────     ─────────────────────    ──────────────────────
FilesystemWatcher ──┐    /Inbox                   /vault-manager
GmailWatcher ───────┤──► /Needs_Action ──────────►/reasoning-loop
WhatsAppWatcher ────┘    /In_Progress             /hitl-workflow
ApprovalWatcher ─────────/Pending_Approval        /email-mcp
                         /Approved                /linkedin-poster
                         /Rejected                /odoo-mcp
                         /Done                    /social-media
                         /Plans                   /whatsapp-watcher
                         /Logs                    /weekly-audit
                         /Social                  /ralph-wiggum
                         /Accounting              /cross-domain
                         /Briefings

MCP Servers              Recovery                 Persistence
─────────────────────    ──────────────────────   ──────────────────────
email_mcp (SMTP)         retry_handler            stop_hook.py
odoo_mcp (Odoo API)      CircuitBreaker           ralph_wiggum.py
social_mcp (FB/TW/IG)    safe_call wrapper        RALPH_* env vars
```

---

## Tier Breakdown

### Bronze (Foundation)
- Obsidian vault with structured folders
- Filesystem watcher: drops files into /Inbox → auto-creates action items
- Claude Code reads/writes vault via `/vault-manager` skill

### Silver (Automation)
- Gmail watcher: monitors unread important emails
- Approval watcher: HITL dispatch (email via SMTP, LinkedIn via Playwright)
- LinkedIn post generator with human-in-the-loop
- Email MCP server (send_email / draft_email)
- Orchestrator: supervised threads with auto-restart
- Scheduler: daily briefings, weekly reports, periodic health checks

### Gold (Full Autonomy)
- WhatsApp watcher: keyword detection via Playwright
- Facebook/Instagram: Graph API v19+ posting
- Twitter/X: API v2 with OAuth 1.0a signing
- Odoo MCP: invoices, revenue, expenses
- Weekly CEO Briefing: Odoo + tasks + social + logs in one report
- Circuit breaker + exponential backoff retry
- Ralph Wiggum persistence loop (stop hook)

---

## Quick Start

### 1. Install dependencies

```bash
pip install watchdog python-dotenv schedule pyyaml
# Gmail (optional)
pip install google-auth google-auth-oauthlib google-api-python-client
# WhatsApp / LinkedIn automation (optional)
pip install playwright && python -m playwright install chromium
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env with your credentials
```

### 3. Start everything

```bash
# All watchers + scheduler
python orchestrator.py --watchers fs,approval

# With Gmail + WhatsApp (after setting up credentials)
python orchestrator.py --watchers fs,gmail,approval,whatsapp
```

### 4. Process items manually

```bash
# Open Claude Code and run:
/vault-manager       # process Needs_Action items
/reasoning-loop      # full triage cycle
/weekly-audit        # generate CEO briefing

# Or use the Ralph Wiggum loop:
python ralph_wiggum.py --batch
```

---

## Credentials Setup

### Gmail

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project → Enable Gmail API → Create OAuth 2.0 credentials (Desktop app)
3. Download `credentials.json` → save as `credentials/gmail_credentials.json`
4. Run: `python -m watchers.gmail_watcher --auth`

### Facebook / Instagram

1. Go to [Meta for Developers](https://developers.facebook.com/)
2. Create an app → Add Facebook Login + Pages API
3. Generate a long-lived Page Access Token
4. Set `FACEBOOK_PAGE_ID` and `FACEBOOK_ACCESS_TOKEN` in `.env`

### Twitter / X

1. Go to [Twitter Developer Portal](https://developer.twitter.com/)
2. Create a project → Enable "Read and Write" permissions
3. Generate API keys and access tokens
4. Set all 4 `TWITTER_*` variables in `.env`

### Odoo

1. Install Odoo Community or use a hosted instance
2. Set `ODOO_URL`, `ODOO_DB`, `ODOO_USER`, `ODOO_PASSWORD` in `.env`
3. Test: `python -c "from odoo.client import OdooClient; c = OdooClient(); print(c.ping())"`

---

## MCP Servers

All three MCP servers are registered in `.mcp.json` and available to Claude Code:

| Server | Tools | Approval |
|--------|-------|----------|
| `email` | `send_email`, `draft_email` | send requires HITL |
| `odoo` | `get_revenue_summary`, `list_invoices`, `create_draft_invoice` | posting requires HITL |
| `social` | `post_facebook`, `post_instagram`, `post_twitter`, `get_social_summary` | all posts require HITL |

---

## Agent Skills

All capabilities are exposed as Claude Code Agent Skills (`.claude/skills/`):

| Skill | Tier | Description |
|-------|------|-------------|
| `vault-manager` | Bronze | Vault read/write/triage |
| `gmail-watcher` | Silver | Gmail OAuth setup + monitoring |
| `linkedin-poster` | Silver | LinkedIn post generation + HITL |
| `reasoning-loop` | Silver | Full triage cycle |
| `hitl-workflow` | Silver | Approval file management |
| `email-mcp` | Silver | SMTP email via MCP |
| `odoo-mcp` | Gold | Odoo accounting via MCP |
| `social-media` | Gold | FB/Instagram/Twitter via MCP |
| `whatsapp-watcher` | Gold | WhatsApp keyword monitoring |
| `weekly-audit` | Gold | CEO briefing generation |
| `ralph-wiggum` | Gold | Persistence loop (stop hook) |
| `cross-domain` | Gold | Multi-system orchestration |

---

## Lessons Learned

1. **File-based state is resilient** — vault folders survive crashes, reboots, and context loss
2. **HITL by default** — making approval the default prevents costly mistakes
3. **Circuit breakers matter** — external APIs fail; graceful degradation keeps the system running
4. **Skills > prompts** — Agent Skills make complex workflows repeatable and auditable
5. **FIFO + claim-by-move** — prevents duplicate processing in multi-agent scenarios
6. **Stop hooks enable persistence** — the Ralph Wiggum loop eliminates "one-and-done" failures
7. **Audit logs are invaluable** — structured JSON logs make debugging and reporting trivial

---

## File Structure

```
Employee-AI/
├── .claude/
│   ├── settings.json          # Stop hook registration
│   └── skills/                # 13 Agent Skills
├── AI_Employee_Vault/         # Obsidian vault
│   ├── Dashboard.md
│   ├── Company_Handbook.md
│   ├── Inbox/
│   ├── Needs_Action/
│   ├── In_Progress/
│   ├── Plans/
│   ├── Pending_Approval/
│   ├── Approved/
│   ├── Rejected/
│   ├── Done/
│   ├── Logs/
│   ├── Social/
│   ├── Accounting/
│   └── Briefings/
├── watchers/
│   ├── base_watcher.py
│   ├── filesystem_watcher.py
│   ├── gmail_watcher.py
│   ├── approval_watcher.py
│   └── whatsapp_watcher.py
├── linkedin/post_generator.py
├── social/
│   ├── facebook_poster.py
│   └── twitter_poster.py
├── odoo/client.py
├── mcp_servers/
│   ├── email_mcp.py
│   ├── odoo_mcp.py
│   └── social_mcp.py
├── audit/
│   ├── audit_logger.py
│   └── weekly_audit.py
├── recovery/retry_handler.py
├── hooks/stop_hook.py
├── orchestrator.py
├── scheduler.py
├── ralph_wiggum.py
├── .mcp.json
├── .env.example
└── pyproject.toml
```

---

*Built for Hackathon 0 — Personal AI Employee in 2026*
