---
name: linkedin-poster
description: |
  Generate LinkedIn posts from vault data and post to LinkedIn via Playwright.
  Use when the user wants to generate business content for LinkedIn, schedule
  posts, or manually post via browser automation. Always requires human approval
  before posting (HITL workflow).
---

# LinkedIn Poster

Generate professional LinkedIn posts from vault data and post via Playwright automation.

## Workflow Overview

```
1. Generate post content  →  Pending_Approval/LINKEDIN_<date>.md
2. Human reviews & edits  →  Move to Approved/
3. Approval Watcher posts →  LinkedIn published  →  Moved to Done/
```

## Step 1 — Generate a Post

```bash
# Generate using a template (insight / milestone / tips / story)
python -m linkedin.post_generator --template insight
python -m linkedin.post_generator --template milestone
python -m linkedin.post_generator --template tips

# With a custom topic
python -m linkedin.post_generator --template story --topic "AI automation in small business"
```

The post draft is saved to `AI_Employee_Vault/Pending_Approval/LINKEDIN_<date>_<template>.md`

## Step 2 — Review & Approve

Open the file in Obsidian or any editor:
- Edit the **Post Content** section if needed
- Move the file to `AI_Employee_Vault/Approved/`

The Approval Watcher (running via orchestrator) picks it up and posts.

## Step 3 — Manual Posting (Playwright)

If the Approval Watcher is not running, post manually using Playwright:

### Start Playwright MCP server first
```bash
bash .claude/skills/browsing-with-playwright/scripts/start-server.sh
```

### Log in to LinkedIn (first time)
```bash
python3 .claude/skills/browsing-with-playwright/scripts/mcp-client.py call \
  -u http://localhost:8808 -t browser_navigate -p '{"url": "https://www.linkedin.com/login"}'
```
Log in manually in the browser window, then the session is saved.

### Post content
```bash
# Navigate to feed
python3 .claude/skills/browsing-with-playwright/scripts/mcp-client.py call \
  -u http://localhost:8808 -t browser_navigate -p '{"url": "https://www.linkedin.com/feed/"}'

# Take snapshot to find the "Start a post" button
python3 .claude/skills/browsing-with-playwright/scripts/mcp-client.py call \
  -u http://localhost:8808 -t browser_snapshot -p '{}'

# Click "Start a post" (use ref from snapshot)
python3 .claude/skills/browsing-with-playwright/scripts/mcp-client.py call \
  -u http://localhost:8808 -t browser_click -p '{"element": "Start a post", "ref": "<ref-from-snapshot>"}'

# Type post content
python3 .claude/skills/browsing-with-playwright/scripts/mcp-client.py call \
  -u http://localhost:8808 -t browser_type \
  -p '{"element": "post text area", "ref": "<ref>", "text": "Your post content here"}'

# Click Post button
python3 .claude/skills/browsing-with-playwright/scripts/mcp-client.py call \
  -u http://localhost:8808 -t browser_click -p '{"element": "Post button", "ref": "<ref>"}'
```

## Post Templates

| Template  | Best For |
|-----------|----------|
| `insight` | Business lessons, observations |
| `milestone` | Completed projects, achievements |
| `tips` | Industry tips (3-point format) |
| `story` | Behind-the-scenes narratives |

## Configure Business Context

Edit `.env` to personalize posts:
```
LINKEDIN_BUSINESS=Your Company Name
LINKEDIN_INDUSTRY=software consulting
LINKEDIN_TONE=professional
```

Or update `Company_Handbook.md`:
```
Business Name : Your Company Name
```

## Scheduled Auto-Generation

The scheduler generates a LinkedIn post every Sunday at 20:00:
```bash
# Run scheduler standalone
python scheduler.py

# Or run via orchestrator (recommended)
python orchestrator.py
```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Playwright not running | Run `bash .claude/skills/browsing-with-playwright/scripts/start-server.sh` |
| Not logged in to LinkedIn | Navigate to linkedin.com/login manually in the browser |
| Post button not found | Run `browser_snapshot` to get current element refs |
| Session expired | Close browser, restart Playwright MCP, log in again |
