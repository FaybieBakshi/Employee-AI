# Skill: platinum-demo

## Purpose
Step-by-step verification of the Platinum Tier end-to-end demo.
Use this skill to run, check, or troubleshoot the full Cloud → Local pipeline.

---

## Demo Overview

**Flow**: Email arrives → Cloud triages → Draft reply pushed to Pending_Approval/cloud/
         → Git sync → Local pulls → Human approves → Local sends → Done

---

## Prerequisites

Before running the demo, verify:
- [ ] Vault exists at `AI_Employee_Vault/`
- [ ] Subdomain folders exist: `Needs_Action/cloud/`, `Pending_Approval/cloud/`, etc.
- [ ] `.env` or `.env.cloud` has `AGENT_ROLE`, `DRY_RUN=true`
- [ ] Python 3.13+ installed
- [ ] `python -c "import orchestrator; import web_dashboard"` passes (no import errors)

---

## Terminal Setup

Open 3 terminals in the project root.

### Terminal 1 — Simulated Cloud Agent
```bash
AGENT_ROLE=cloud DRY_RUN=true python cloud/orchestrator_cloud.py --watchers fs
```

Expected output:
```
[INFO] cloud.orchestrator: Cloud Agent Orchestrator starting (Platinum Tier)
[INFO] cloud.orchestrator:   Started: CloudActionProcessor
[INFO] cloud.orchestrator:   Started: HealthMonitor
[INFO] cloud.orchestrator:   Started: VaultSync[cloud]
```

### Terminal 2 — Local Agent
```bash
python orchestrator.py --role local --watchers fs,approval,sync,signals
```

Expected output:
```
[INFO] orchestrator: AI Employee Orchestrator starting
[INFO] orchestrator:   Started: FilesystemWatcher
[INFO] orchestrator:   Started: ApprovalWatcher
[INFO] orchestrator:   Started: VaultSync
[INFO] orchestrator:   Started: SignalProcessor
```

### Terminal 3 — Dashboard (optional)
```bash
python web_dashboard.py
# Browse to http://localhost:8080
```

---

## Test Sequence

### Step 1: Inject a test email action file
```bash
cat > AI_Employee_Vault/Needs_Action/cloud/EMAIL_test_001.md << 'EOF'
---
type: email
id: test_001
from: test@example.com
subject: Test Platinum Demo
date: 2026-03-02T10:00:00Z
---
Hello,

This is a test email for the Platinum demo. Please advise on our contract renewal.

Best regards,
Test User
EOF
```

### Step 2: Verify claim
Watch Terminal 1 for:
```
[INFO] cloud.claim_manager: Claimed: EMAIL_test_001.md → In_Progress/cloud/
[INFO] cloud.ActionProcessor: Processing: EMAIL_test_001.md
```

Verify file moved:
```bash
ls AI_Employee_Vault/In_Progress/cloud/   # should show EMAIL_test_001.md
```

### Step 3: Verify draft created (DRY_RUN)
With `DRY_RUN=true`, Claude is not invoked but the processor logs the claim.
Expected log:
```
[INFO] cloud.ActionProcessor: [DRY_RUN] Would invoke Claude for: EMAIL_test_001.md
```

To test full Claude invocation (requires Claude Code installed):
```bash
AGENT_ROLE=cloud DRY_RUN=false python cloud/orchestrator_cloud.py --watchers fs
```
Verify: `AI_Employee_Vault/Pending_Approval/cloud/` contains a draft file.

### Step 4: Verify git sync (DRY_RUN skips push)
With a real git remote configured, Terminal 1 VaultSync would push.
Check sync log:
```
[INFO] sync.VaultSync[cloud]: ...
```

### Step 5: Simulate approval
Move a draft to Approved/:
```bash
mkdir -p AI_Employee_Vault/Approved
mv AI_Employee_Vault/Pending_Approval/cloud/APPROVAL_*.md AI_Employee_Vault/Approved/
```

Watch Terminal 2 ApprovalWatcher for:
```
[INFO] ApprovalWatcher: Processing approval: APPROVAL_*.md
[DRY_RUN] Would send email: ...
```

### Step 6: Verify health signal
```bash
cat AI_Employee_Vault/Signals/health_cloud.json
```

Expected:
```json
{
  "agent": "cloud",
  "status": "healthy",
  "timestamp": "2026-03-02T...",
  "checks": { "odoo": "...", "smtp": "ok", "disk_free_gb": ..., "git": "ok" }
}
```

### Step 7: Verify signal processor updated Dashboard
```bash
grep -A 10 "System Status" AI_Employee_Vault/Dashboard.md
```

---

## Verification Checklist

| Check | Command | Expected |
|---|---|---|
| Imports pass | `python -c "import orchestrator; import web_dashboard"` | No errors |
| Cloud package | `python -c "import cloud.orchestrator_cloud"` | No errors |
| Sync package | `python -c "import sync.vault_sync; import sync.signal_processor"` | No errors |
| Vault folders | `ls AI_Employee_Vault/Needs_Action/` | Shows `cloud/` and `local/` |
| Health check | `python cloud/health_monitor.py --once` | JSON with status |
| Single sync | `python sync/vault_sync.py --role local --once` | No error (may be up-to-date) |

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError: cloud` | Ensure `cloud/__init__.py` exists; run from project root |
| `ModuleNotFoundError: sync` | Ensure `sync/__init__.py` exists |
| `Vault not found` | Check `VAULT_PATH` env var; default is `AI_Employee_Vault` relative to CWD |
| File not claimed | Check `Needs_Action/cloud/` folder exists; check ClaimManager source path |
| Git push fails | Verify `SSH_KEY_PATH`, deploy key added to repo, `GIT_REMOTE_URL` set |
| Health shows `skipped` | Normal for `ODOO_URL` not set; set env var to enable check |
