---
name: reasoning-loop
description: |
  Full reasoning loop: reads Company_Handbook.md, processes all Needs_Action
  items (FIFO), creates Plan files, executes auto-approved actions, creates
  approval files for sensitive actions, moves items to Done, and updates
  Dashboard. Use this as the primary "work session" trigger for Claude.
---

# Reasoning Loop

Full autonomous work cycle: triage → plan → act → log → complete.

## When to Use

Run this skill when:
- New files have appeared in `Needs_Action/`
- The orchestrator triggers a processing cycle
- You want Claude to work through all pending items

## The Loop (execute in order)

### Phase 1 — Context Loading

```
1. Read AI_Employee_Vault/Company_Handbook.md  → internalize all rules
2. Read AI_Employee_Vault/Dashboard.md          → understand current state
3. List AI_Employee_Vault/Needs_Action/*.md     → find all pending items
4. Sort by file creation date (oldest first — FIFO per Handbook §4)
```

### Phase 2 — Process Each Item

For **each** file in Needs_Action (oldest first):

```
a. Read the action file fully
b. Classify the task type (email, file_drop, approval_request, etc.)
c. Determine required actions (check Handbook §3 for approval thresholds)
d. Create Plan_<filename>.md in Plans/
e. Execute auto-approved actions immediately
f. Create APPROVAL_*.md in Pending_Approval/ for sensitive actions
g. Move the action file to Done/
h. Log the action to Logs/YYYY-MM-DD.json
```

### Phase 3 — Completion

```
1. Update Dashboard.md (counts + recent activity)
2. Write session summary to Logs/YYYY-MM-DD.json
3. Report: items processed, plans created, approvals pending
```

## Plan File Format

```markdown
---
created: 2026-02-28T10:00:00Z
source: FILE_report_q1.pdf.md
status: completed
---

## Objective
Process quarterly report drop from Inbox.

## Steps
- [x] Read source file metadata
- [x] Determine action: summarize and file
- [x] Create summary in Plans/
- [x] Move to Done/

## Decision Log
- 2026-02-28: File identified as report — no sensitive data, auto-processed
```

## Action Classification Rules

| File prefix  | Typical action          | Approval needed? |
|--------------|-------------------------|:----------------:|
| `EMAIL_`     | Draft reply             | Yes (send_email) |
| `FILE_`      | Summarize or file       | No               |
| `WHATSAPP_`  | Draft reply             | Yes              |
| `APPROVAL_`  | Wait — do not re-process| —                |

## Approval File Format

For actions requiring approval, write to `Pending_Approval/`:

```markdown
---
type: approval_request
action: send_email
to: "client@example.com"
subject: "Re: Your inquiry"
created: 2026-02-28T10:00:00Z
status: pending
---

## Email Draft

[email body here]

## To Approve
Move to AI_Employee_Vault/Approved/

## To Reject
Move to AI_Employee_Vault/Rejected/
```

## Dashboard Update Format

After processing, update these sections in Dashboard.md:

```markdown
## Inbox Summary
| Needs Action | 0 |
| Plans Active | 3 |
| Done (today) | 5 |

## Recent Activity
- [2026-02-28 10:30 UTC] Processed 5 items — 3 plans created, 2 approvals pending
```

## Stopping Condition

The loop is complete when:
- All `.md` files in `Needs_Action/` have been moved to `Done/`
- Dashboard has been updated
- Log entry has been written

If a task cannot be completed, write a Plan with `status: blocked` and explain why.
Never silently skip items. Never leave Needs_Action files unprocessed.
