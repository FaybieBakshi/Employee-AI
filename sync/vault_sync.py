"""
vault_sync.py — Git push/pull for the shared AI Employee Vault (Platinum Tier).

Cloud agent: stages only cloud-owned paths, commits, pushes.
Local agent: pulls with rebase; cloud-path conflicts → cloud wins;
             Dashboard.md conflicts → local wins (cloud never commits it).

Single-writer rule
  - Cloud commits: Needs_Action/cloud/, Plans/cloud/, Pending_Approval/cloud/,
                   In_Progress/cloud/, Updates/, Signals/
  - Local commits: everything else, including Dashboard.md

Usage (standalone):
  python sync/vault_sync.py --role cloud   # run cloud sync loop
  python sync/vault_sync.py --role local   # run local pull loop
  python sync/vault_sync.py --once         # single sync then exit

Environment variables:
  GIT_REMOTE_URL    — git remote (default: origin)
  SYNC_INTERVAL     — seconds between syncs (default: 60)
  VAULT_PATH        — path to vault (default: AI_Employee_Vault)
  AGENT_ROLE        — cloud | local (default: local)
  SSH_KEY_PATH      — path to SSH key for git (optional)
"""

import argparse
import logging
import os
import subprocess
import threading
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("sync.vault_sync")

VAULT_PATH = Path(os.getenv("VAULT_PATH", "AI_Employee_Vault")).resolve()
AGENT_ROLE = os.getenv("AGENT_ROLE", "local")
GIT_REMOTE_URL = os.getenv("GIT_REMOTE_URL", "")
SYNC_INTERVAL = int(os.getenv("SYNC_INTERVAL", "60"))
SSH_KEY_PATH = os.getenv("SSH_KEY_PATH", "")

# Paths owned by the cloud agent (relative to vault root)
CLOUD_OWNED_PATHS = [
    "Needs_Action/cloud",
    "Plans/cloud",
    "Pending_Approval/cloud",
    "In_Progress/cloud",
    "Updates",
    "Signals",
]


def _git_env() -> dict:
    """Build environment with optional SSH key override."""
    env = os.environ.copy()
    if SSH_KEY_PATH:
        key = Path(SSH_KEY_PATH).expanduser()
        if key.exists():
            env["GIT_SSH_COMMAND"] = f'ssh -i "{key}" -o StrictHostKeyChecking=no'
    return env


def _run_git(args: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    """Run a git command and return (returncode, stdout, stderr)."""
    cmd = ["git"] + args
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(cwd or VAULT_PATH.parent),
        env=_git_env(),
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def _repo_root() -> Path:
    """Return the git repo root (parent of vault or vault itself)."""
    rc, out, _ = _run_git(["rev-parse", "--show-toplevel"])
    if rc == 0:
        return Path(out)
    return VAULT_PATH.parent


def sync_cloud_push() -> bool:
    """
    Stage cloud-owned vault paths, commit if there are changes, push to remote.
    Returns True if a push was made.
    """
    repo_root = _repo_root()
    vault_rel = VAULT_PATH.relative_to(repo_root)

    # Stage only cloud-owned paths
    staged_any = False
    for rel_path in CLOUD_OWNED_PATHS:
        full_path = VAULT_PATH / rel_path
        if full_path.exists():
            git_path = str(vault_rel / rel_path)
            rc, _, err = _run_git(["add", git_path], cwd=repo_root)
            if rc != 0:
                logger.warning(f"git add {git_path} failed: {err}")
            else:
                staged_any = True

    if not staged_any:
        return False

    # Check if anything is actually staged
    rc, diff_out, _ = _run_git(["diff", "--cached", "--name-only"], cwd=repo_root)
    if rc != 0 or not diff_out:
        logger.debug("No staged changes to commit")
        return False

    # Commit
    commit_msg = f"cloud: sync {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}"
    rc, _, err = _run_git(["commit", "-m", commit_msg], cwd=repo_root)
    if rc != 0:
        logger.error(f"git commit failed: {err}")
        return False
    logger.info(f"Committed: {commit_msg}")

    # Push
    remote = GIT_REMOTE_URL or "origin"
    rc, _, err = _run_git(["push", remote, "HEAD"], cwd=repo_root)
    if rc != 0:
        logger.error(f"git push failed: {err}")
        return False

    logger.info("Pushed to remote successfully")
    return True


def sync_local_pull() -> bool:
    """
    Pull remote changes with rebase.
    On conflict: cloud paths → cloud wins (--theirs); Dashboard.md → local wins (--ours).
    Returns True if new commits were pulled.
    """
    repo_root = _repo_root()
    remote = GIT_REMOTE_URL or "origin"

    # Fetch
    rc, _, err = _run_git(["fetch", remote], cwd=repo_root)
    if rc != 0:
        logger.error(f"git fetch failed: {err}")
        return False

    # Check if behind remote
    rc, behind, _ = _run_git(["rev-list", "--count", "HEAD..FETCH_HEAD"], cwd=repo_root)
    if rc != 0 or behind == "0":
        logger.debug("Already up to date")
        return False

    logger.info(f"Pulling {behind} new commit(s) from remote")
    rc, out, err = _run_git(["rebase", "FETCH_HEAD"], cwd=repo_root)
    if rc == 0:
        logger.info("Rebase successful")
        return True

    # Handle conflicts
    logger.warning(f"Rebase conflict detected: {err}")
    _resolve_conflicts(repo_root)
    _run_git(["rebase", "--continue"], cwd=repo_root)
    return True


def _resolve_conflicts(repo_root: Path) -> None:
    """Resolve rebase conflicts per single-writer rules."""
    rc, conflict_files, _ = _run_git(
        ["diff", "--name-only", "--diff-filter=U"], cwd=repo_root
    )
    if rc != 0:
        return

    vault_prefix = str(VAULT_PATH.relative_to(repo_root))

    for rel_file in conflict_files.splitlines():
        is_cloud_path = any(
            rel_file.startswith(f"{vault_prefix}/{p}") for p in CLOUD_OWNED_PATHS
        )
        is_dashboard = rel_file.endswith("Dashboard.md")

        if is_cloud_path:
            logger.info(f"Conflict on cloud path {rel_file} → cloud wins (--theirs)")
            _run_git(["checkout", "--theirs", rel_file], cwd=repo_root)
        elif is_dashboard:
            logger.info(f"Conflict on Dashboard.md → local wins (--ours)")
            _run_git(["checkout", "--ours", rel_file], cwd=repo_root)
        else:
            logger.warning(f"Conflict on {rel_file} → defaulting to theirs")
            _run_git(["checkout", "--theirs", rel_file], cwd=repo_root)

        _run_git(["add", rel_file], cwd=repo_root)


# ──────────────────────────────────────────────────────────────────────
# VaultSync — runnable class for use in WatcherThread / Orchestrator
# ──────────────────────────────────────────────────────────────────────

class VaultSync:
    """
    Long-running sync loop.  Use run() to block, or start() for a background thread.

    role="cloud" → push loop
    role="local" → pull loop
    """

    def __init__(self, role: str = AGENT_ROLE, interval: int = SYNC_INTERVAL):
        self.role = role
        self.interval = interval
        self._stop = threading.Event()
        self.logger = logging.getLogger(f"sync.VaultSync[{role}]")

    def run(self) -> None:
        self.logger.info(
            f"VaultSync starting (role={self.role}, interval={self.interval}s)"
        )
        while not self._stop.is_set():
            try:
                if self.role == "cloud":
                    sync_cloud_push()
                else:
                    sync_local_pull()
            except Exception as err:
                self.logger.error(f"Sync error: {err}")
            self._stop.wait(self.interval)

    def stop(self) -> None:
        self._stop.set()


# ──────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    parser = argparse.ArgumentParser(description="Vault sync (Platinum Tier)")
    parser.add_argument("--role", choices=["cloud", "local"], default=AGENT_ROLE)
    parser.add_argument("--interval", type=int, default=SYNC_INTERVAL)
    parser.add_argument("--once", action="store_true", help="Sync once and exit")
    args = parser.parse_args()

    if args.once:
        if args.role == "cloud":
            sync_cloud_push()
        else:
            sync_local_pull()
        return

    vs = VaultSync(role=args.role, interval=args.interval)
    vs.run()


if __name__ == "__main__":
    main()
