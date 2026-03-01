---
name: gmail-watcher
description: |
  Set up, configure, and run the Gmail Watcher. Monitors Gmail for unread
  important emails and creates Needs_Action files in the vault. Use when
  the user wants to start Gmail monitoring or troubleshoot email detection.
---

# Gmail Watcher

Monitor Gmail for important emails and route them to the vault for processing.

## One-Time Setup (required before first run)

### Step 1 — Google Cloud Setup
1. Go to [console.cloud.google.com](https://console.cloud.google.com)
2. Create a new project (or select existing)
3. Enable the **Gmail API**: APIs & Services → Library → search "Gmail API" → Enable
4. Create credentials: APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID
5. Application type: **Desktop app**
6. Download JSON → rename to `gmail_credentials.json`
7. Move to: `credentials/gmail_credentials.json`

```bash
mkdir -p credentials
mv ~/Downloads/client_secret_*.json credentials/gmail_credentials.json
```

### Step 2 — OAuth Authorization (one-time)
```bash
python -m watchers.gmail_watcher --auth
```
Browser opens → sign in → grant access → token saved to `credentials/gmail_token.json`

### Step 3 — Install dependencies
```bash
pip install google-auth google-auth-oauthlib google-api-python-client
```

### Step 4 — Configure .env
```
GMAIL_CREDENTIALS_PATH=credentials/gmail_credentials.json
GMAIL_TOKEN_PATH=credentials/gmail_token.json
GMAIL_CHECK_INTERVAL=120
GMAIL_QUERY=is:unread is:important
DRY_RUN=true
```

## Running

```bash
# Start watcher (polls every 2 minutes)
python -m watchers.gmail_watcher

# Custom query — e.g. monitor specific label
python -m watchers.gmail_watcher --query "label:client-requests is:unread"

# Dry run (default) — creates action files but marks them as dry_run
python -m watchers.gmail_watcher --dry-run
```

## What It Creates

For each detected email, a file appears in `AI_Employee_Vault/Needs_Action/`:

```
EMAIL_<message_id>.md
```

With frontmatter:
```yaml
type: email
from: "sender@example.com"
subject: "Project Update"
priority: high
status: pending
```

## Processing Detected Emails

After the watcher creates action files, run `/vault-manager` or `/reasoning-loop`
to have Claude process them:

1. Claude reads `EMAIL_*.md` files
2. Determines if reply is needed
3. Drafts reply → saves to `Pending_Approval/` (requires approval)
4. Or archives it directly to `Done/`

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `credentials not found` | Run `--auth` flag first |
| `403 Forbidden` | Verify Gmail API is enabled in Google Cloud Console |
| `Token expired` | Delete `credentials/gmail_token.json` and re-run `--auth` |
| `No emails detected` | Check `--query` matches your inbox; try `is:unread` |
| Watcher stops overnight | Use orchestrator.py or PM2 for process management |
