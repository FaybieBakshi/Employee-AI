# Skill: vault-sync

## Purpose
Manage Git-backed vault synchronisation between Cloud Agent (Ubuntu VM) and
Local Agent (Windows). This skill describes the sync protocol, single-writer
rules, and conflict resolution strategy.

---

## Architecture

```
Cloud VM (Ubuntu, 24/7)            Local Machine (Windows)
─────────────────────              ──────────────────────
VaultSync.run(role="cloud")        VaultSync.run(role="local")
    │                                   │
    ├─ git add <cloud-owned paths>      ├─ git fetch origin
    ├─ git commit "cloud: sync ..."     ├─ git rebase FETCH_HEAD
    └─ git push origin HEAD             └─ Conflict resolution
                                            Cloud paths → --theirs
                                            Dashboard.md → --ours
```

---

## Single-Writer Rule

Each path has exactly one writer. Violating this causes merge conflicts.

| Path pattern | Writer | Commit rule |
|---|---|---|
| `Needs_Action/cloud/**` | Cloud | Cloud stages + commits |
| `Plans/cloud/**` | Cloud | Cloud stages + commits |
| `Pending_Approval/cloud/**` | Cloud | Cloud stages + commits |
| `In_Progress/cloud/**` | Cloud | Cloud stages + commits |
| `Updates/**` | Cloud | Cloud stages + commits |
| `Signals/**` | Cloud | Cloud stages + commits |
| `Dashboard.md` | Local | Local stages + commits; Cloud **never** commits |
| Everything else | Local | Local stages + commits |

---

## Cloud Push Protocol

```python
# sync/vault_sync.py — sync_cloud_push()
CLOUD_OWNED_PATHS = [
    "Needs_Action/cloud",
    "Plans/cloud",
    "Pending_Approval/cloud",
    "In_Progress/cloud",
    "Updates",
    "Signals",
]
# git add <path> for each cloud-owned path
# git commit -m "cloud: sync <ISO timestamp>"
# git push origin HEAD
```

Cloud never runs `git add .` or `git add -A`.

---

## Local Pull Protocol

```python
# sync/vault_sync.py — sync_local_pull()
# git fetch origin
# git rebase FETCH_HEAD
# On conflict:
#   cloud paths  → git checkout --theirs <file>
#   Dashboard.md → git checkout --ours <file>
#   other        → git checkout --theirs <file>  (safe default)
# git rebase --continue
```

---

## Conflict Resolution Rules

1. **Cloud-owned paths**: Cloud wins (`--theirs`). Cloud is the authoritative
   source for its domain. Local never modifies these paths.

2. **Dashboard.md**: Local wins (`--ours`). Only the Local agent writes
   Dashboard.md. Cloud never commits Dashboard.md.

3. **Other files** (neither cloud-owned nor Dashboard.md): Default to
   `--theirs` (remote/cloud) and log a warning.

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `GIT_REMOTE_URL` | `origin` | Remote URL or alias |
| `SYNC_INTERVAL` | `60` | Seconds between sync cycles |
| `SSH_KEY_PATH` | — | Path to SSH deploy key (cloud only) |
| `AGENT_ROLE` | `local` | Determines push vs pull mode |

---

## Running Sync

```bash
# Cloud agent (push loop)
python sync/vault_sync.py --role cloud --interval 60

# Local agent (pull loop)
python sync/vault_sync.py --role local --interval 60

# Single sync (useful for cron)
python sync/vault_sync.py --role cloud --once
python sync/vault_sync.py --role local --once

# Via orchestrator
python orchestrator.py --role local --watchers fs,approval,sync,signals
```

---

## Troubleshooting

| Symptom | Resolution |
|---|---|
| `git push` rejected (non-fast-forward) | Local has unpushed commits; do `git pull --rebase` on cloud first |
| Merge conflict on `Dashboard.md` | Local wins; run `git checkout --ours Dashboard.md && git add Dashboard.md` |
| `SSH authentication failed` | Verify `SSH_KEY_PATH` and that deploy key is added to repo |
| Cloud path not syncing | Check `CLOUD_OWNED_PATHS` in `vault_sync.py`; verify `git add` is not failing |
