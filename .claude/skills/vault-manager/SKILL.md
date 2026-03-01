---
name: vault-manager
description: |
  Manages the AI Employee Obsidian vault. Reads Company_Handbook.md for rules,
  processes files from /Needs_Action, creates Plan files, updates Dashboard.md,
  moves completed items to /Done, and writes audit logs. Use when you need to
  triage tasks, process inbox items, or update the vault state.
---

# Vault Manager

Read and write the AI Employee vault: process tasks, create plans, update the dashboard.

## Before Every Action

1. Read `AI_Employee_Vault/Company_Handbook.md` — follow its rules
2. Read `AI_Employee_Vault/Dashboard.md` — understand current state
3. Check `AI_Employee_Vault/Needs_Action/` — list pending items

## Vault Structure

```
AI_Employee_Vault/
├── Dashboard.md          ← Real-time status (update after every session)
├── Company_Handbook.md   ← Rules of engagement (read-only)
├── Inbox/                ← Drop zone (do not process directly)
├── Needs_Action/         ← Items to process (created by watchers)
├── Plans/                ← Plans you create (one per task)
├── Done/                 ← Completed items (move here when finished)
└── Logs/                 ← Audit logs (JSON, one file per day)
```

## Workflow: Process Needs_Action

```
1. List all .md files in Needs_Action/
2. Sort by creation date (oldest first — FIFO)
3. For each item:
   a. Read the action file
   b. Determine what needs to be done
   c. Create Plan_<filename>.md in Plans/
   d. Execute auto-approved actions (see Handbook §3)
   e. Write approval files for sensitive actions
   f. Move action file to Done/
4. Update Dashboard.md
5. Write log entry to Logs/YYYY-MM-DD.json
```

## Creating a Plan File

Save to `AI_Employee_Vault/Plans/Plan_<task_name>.md`:

```markdown
---
created: <ISO timestamp>
source: <Needs_Action filename>
status: in_progress
---

## Objective
<one sentence>

## Steps
- [x] Step already done
- [ ] Step to do

## Decision Log
- <date>: <what was decided and why>
```

## Updating Dashboard.md

After each processing session, update these sections in Dashboard.md:

- **System Status** table — mark watcher as On/Off based on reality
- **Inbox Summary** — recount files in each folder
- **Recent Activity** — prepend a new line: `- [YYYY-MM-DD HH:MM] <what happened>`

Use the Read tool to get current counts:
```bash
# Count files in each folder (excluding .gitkeep)
ls AI_Employee_Vault/Needs_Action/
ls AI_Employee_Vault/Done/
ls AI_Employee_Vault/Plans/
```

## Writing Audit Logs

Append to `AI_Employee_Vault/Logs/YYYY-MM-DD.json`:

```json
[
  {
    "timestamp": "2026-02-28T10:30:00Z",
    "action_type": "plan_created",
    "actor": "claude_code",
    "target": "Plan_report_q1.pdf.md",
    "result": "success"
  }
]
```

## Moving Files to Done

Move (rename) using the Bash tool:
```bash
mv "AI_Employee_Vault/Needs_Action/FILE_example.md" "AI_Employee_Vault/Done/FILE_example.md"
mv "AI_Employee_Vault/Plans/Plan_example.md" "AI_Employee_Vault/Done/Plan_example.md"
```

## Creating Approval Files

For sensitive actions (email, payments), write to `AI_Employee_Vault/Needs_Action/`:

```markdown
---
type: approval_request
action: <action type>
target: <who/what>
reason: <why>
created: <ISO timestamp>
status: pending
---

## Action Requested
<description>

## To Approve
Move this file to AI_Employee_Vault/Done/ and re-run /vault-manager.

## To Reject
Delete this file.
```

## Verification

After running, confirm:
- [ ] Dashboard.md `last_updated` field is today's date
- [ ] All processed Needs_Action items are in Done/
- [ ] A Plan file exists for each processed item
- [ ] Log entry written to Logs/YYYY-MM-DD.json

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Vault folders missing | Run `mkdir -p AI_Employee_Vault/{Inbox,Needs_Action,Done,Plans,Logs}` |
| No items to process | Drop a file into `AI_Employee_Vault/Inbox/` and run the filesystem watcher |
| Dashboard out of date | Re-run `/vault-manager` to trigger a dashboard refresh |
