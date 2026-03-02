"""
orchestrator.py — Master process for the AI Employee (Gold / Platinum Tier).

Manages all watcher processes and the scheduler in a single command.
Each watcher runs as a supervised background thread; crashed watchers
are restarted automatically.

Also provides the trigger mechanism to invoke Claude Code for reasoning.

Usage:
  python orchestrator.py                            # start all watchers + scheduler
  python orchestrator.py --watchers fs              # filesystem watcher only
  python orchestrator.py --watchers fs,approval,whatsapp  # specific watchers
  python orchestrator.py --no-scheduler             # skip scheduler
  python orchestrator.py --role cloud               # delegate to cloud agent
  python orchestrator.py --role local --watchers fs,approval,sync,signals

Platinum Tier roles:
  --role local (default) — Gold-compatible; optionally adds sync/signals watchers
  --role cloud           — delegates entirely to cloud.orchestrator_cloud.main()

Environment variables (.env):
  VAULT_PATH       — path to vault (default: AI_Employee_Vault)
  DRY_RUN          — if "true", watchers log instead of act (default: true)
  ENABLE_GMAIL     — if "true", start Gmail watcher (needs credentials)
  ENABLE_WHATSAPP  — if "true", start WhatsApp watcher (needs Playwright)
  AGENT_ROLE       — cloud | local (default: local) — overridden by --role
"""

import argparse
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("orchestrator")

VAULT_PATH = Path(os.getenv("VAULT_PATH", "AI_Employee_Vault")).resolve()
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
ENABLE_GMAIL = os.getenv("ENABLE_GMAIL", "false").lower() == "true"
ENABLE_WHATSAPP = os.getenv("ENABLE_WHATSAPP", "false").lower() == "true"
AGENT_ROLE = os.getenv("AGENT_ROLE", "local")


# ──────────────────────────────────────────────────────────────────────
# Supervised watcher thread
# ──────────────────────────────────────────────────────────────────────

class WatcherThread(threading.Thread):
    """
    Runs a watcher in a daemon thread.
    If the watcher crashes, waits RESTART_DELAY seconds then restarts it.
    """

    RESTART_DELAY = 10  # seconds

    def __init__(self, name: str, factory, *args, **kwargs):
        super().__init__(name=name, daemon=True)
        self._factory = factory
        self._args = args
        self._kwargs = kwargs
        self._stop_event = threading.Event()
        self.logger = logging.getLogger(f"orchestrator.{name}")

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.logger.info(f"Starting {self.name}")
                watcher = self._factory(*self._args, **self._kwargs)
                watcher.run()
            except Exception as err:
                self.logger.error(f"{self.name} crashed: {err}")
            if not self._stop_event.is_set():
                self.logger.warning(f"{self.name} stopped. Restarting in {self.RESTART_DELAY}s...")
                time.sleep(self.RESTART_DELAY)

    def stop(self) -> None:
        self._stop_event.set()


# ──────────────────────────────────────────────────────────────────────
# Claude Code trigger
# ──────────────────────────────────────────────────────────────────────

def trigger_claude(prompt: str, cwd: str = None) -> str:
    """
    Invoke Claude Code non-interactively to process a prompt.
    Returns stdout output or error message.

    Requires Claude Code to be installed: npm install -g @anthropic/claude-code
    """
    try:
        result = subprocess.run(
            ["claude", "--print", prompt],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=cwd or str(VAULT_PATH.parent),
        )
        if result.returncode != 0:
            return f"Claude error (code {result.returncode}): {result.stderr[:500]}"
        return result.stdout
    except FileNotFoundError:
        return "ERROR: 'claude' command not found. Install Claude Code first."
    except subprocess.TimeoutExpired:
        return "ERROR: Claude Code timed out after 300 seconds."
    except Exception as err:
        return f"ERROR: {err}"


def process_needs_action() -> None:
    """Trigger Claude to process all pending items in /Needs_Action."""
    needs_action = VAULT_PATH / "Needs_Action"
    pending = [
        f for f in needs_action.iterdir()
        if f.suffix == ".md" and not f.name.startswith(".")
    ]
    if not pending:
        logger.info("Needs_Action is empty — nothing to process")
        return

    logger.info(f"Triggering Claude to process {len(pending)} item(s) in Needs_Action/")
    prompt = (
        f"You are the AI Employee. Vault is at: {VAULT_PATH}\n\n"
        "1. Read Company_Handbook.md and follow all rules.\n"
        "2. Process every file in Needs_Action/ (oldest first, FIFO).\n"
        "3. For each item: create a Plan_<name>.md in Plans/, execute auto-approved actions, "
        "create approval files for sensitive actions.\n"
        "4. Move processed items to Done/.\n"
        "5. Update Dashboard.md.\n"
        "6. Write an audit log entry to Logs/.\n"
    )
    output = trigger_claude(prompt)
    logger.info(f"Claude output:\n{output[:1000]}")


# ──────────────────────────────────────────────────────────────────────
# Scheduler integration
# ──────────────────────────────────────────────────────────────────────

def _run_scheduler() -> None:
    """Run the scheduler in a background thread."""
    try:
        from scheduler import Scheduler
        s = Scheduler(vault_path=str(VAULT_PATH))
        s.run()
    except ImportError:
        logger.warning("scheduler.py not found — skipping scheduled tasks")
    except Exception as err:
        logger.error(f"Scheduler error: {err}")


# ──────────────────────────────────────────────────────────────────────
# Orchestrator
# ──────────────────────────────────────────────────────────────────────

class Orchestrator:
    """Manages all watcher threads and the scheduler."""

    def __init__(self, watchers: list[str], enable_scheduler: bool = True):
        self._threads: list[WatcherThread] = []
        self._scheduler_thread: threading.Thread | None = None
        self.watchers = watchers
        self.enable_scheduler = enable_scheduler

    def _build_threads(self) -> None:
        from watchers.filesystem_watcher import FilesystemWatcher
        from watchers.approval_watcher import ApprovalWatcher

        registry = {
            "fs": ("FilesystemWatcher", FilesystemWatcher, [str(VAULT_PATH)], {}),
            "approval": ("ApprovalWatcher", ApprovalWatcher, [str(VAULT_PATH)], {"dry_run": DRY_RUN}),
        }

        if ENABLE_GMAIL and "gmail" not in self.watchers:
            self.watchers.append("gmail")

        if ENABLE_WHATSAPP and "whatsapp" not in self.watchers:
            self.watchers.append("whatsapp")

        if "whatsapp" in self.watchers:
            try:
                from watchers.whatsapp_watcher import WhatsAppWatcher
                registry["whatsapp"] = (
                    "WhatsAppWatcher",
                    WhatsAppWatcher,
                    [],
                    {
                        "vault_path": str(VAULT_PATH),
                        "session_path": os.getenv("WHATSAPP_SESSION_PATH", ".whatsapp_session"),
                        "dry_run": DRY_RUN,
                    },
                )
            except Exception as err:
                logger.warning(f"WhatsApp watcher unavailable: {err}")

        if "gmail" in self.watchers:
            try:
                from watchers.gmail_watcher import GmailWatcher
                registry["gmail"] = (
                    "GmailWatcher",
                    GmailWatcher,
                    [],
                    {
                        "vault_path": str(VAULT_PATH),
                        "credentials_path": os.getenv("GMAIL_CREDENTIALS_PATH", "credentials/gmail_credentials.json"),
                        "token_path": os.getenv("GMAIL_TOKEN_PATH", "credentials/gmail_token.json"),
                        "dry_run": DRY_RUN,
                    },
                )
            except Exception as err:
                logger.warning(f"Gmail watcher unavailable: {err}")

        if "sync" in self.watchers:
            try:
                from sync.vault_sync import VaultSync
                registry["sync"] = (
                    "VaultSync",
                    VaultSync,
                    [],
                    {
                        "role": os.getenv("AGENT_ROLE", "local"),
                        "interval": int(os.getenv("SYNC_INTERVAL", "60")),
                    },
                )
            except Exception as err:
                logger.warning(f"VaultSync unavailable: {err}")

        if "signals" in self.watchers:
            try:
                from sync.signal_processor import SignalProcessor
                registry["signals"] = (
                    "SignalProcessor",
                    SignalProcessor,
                    [],
                    {"interval": int(os.getenv("SIGNAL_CHECK_INTERVAL", "15"))},
                )
            except Exception as err:
                logger.warning(f"SignalProcessor unavailable: {err}")

        for key in self.watchers:
            if key not in registry:
                logger.warning(f"Unknown watcher: {key!r} — skipping")
                continue
            display_name, factory, args, kwargs = registry[key]
            t = WatcherThread(display_name, factory, *args, **kwargs)
            self._threads.append(t)

    def start(self) -> None:
        if not VAULT_PATH.exists():
            logger.error(f"Vault not found: {VAULT_PATH}")
            raise SystemExit(1)

        logger.info(f"AI Employee Orchestrator starting")
        logger.info(f"  Vault:    {VAULT_PATH}")
        logger.info(f"  Dry run:  {DRY_RUN}")
        logger.info(f"  Watchers: {', '.join(self.watchers)}")

        self._build_threads()

        for thread in self._threads:
            thread.start()
            logger.info(f"  Started: {thread.name}")

        if self.enable_scheduler:
            self._scheduler_thread = threading.Thread(
                target=_run_scheduler, name="Scheduler", daemon=True
            )
            self._scheduler_thread.start()
            logger.info("  Started: Scheduler")

        logger.info("Orchestrator running. Press Ctrl+C to stop.\n")

    def wait(self) -> None:
        try:
            while True:
                time.sleep(5)
                # Periodic Needs_Action check every 5 minutes
                if int(time.time()) % 300 < 5:
                    needs_action = VAULT_PATH / "Needs_Action"
                    pending = [
                        f for f in needs_action.iterdir()
                        if f.suffix == ".md" and not f.name.startswith(".")
                    ]
                    if pending:
                        logger.info(f"{len(pending)} item(s) in Needs_Action — run /reasoning-loop to process")
        except KeyboardInterrupt:
            self.stop()

    def stop(self) -> None:
        logger.info("Stopping all watchers...")
        for thread in self._threads:
            thread.stop()
        logger.info("Orchestrator stopped.")


# ──────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="AI Employee — Orchestrator (Gold / Platinum Tier)"
    )
    parser.add_argument(
        "--role",
        choices=["local", "cloud"],
        default=AGENT_ROLE,
        help="Agent role: 'local' (default, Gold-compatible) or 'cloud' (delegates to cloud agent)",
    )
    parser.add_argument(
        "--watchers",
        default="fs,approval",
        help=(
            "Comma-separated watcher names: fs, gmail, approval, whatsapp, sync, signals "
            "(default: fs,approval)"
        ),
    )
    parser.add_argument(
        "--no-scheduler",
        action="store_true",
        help="Disable the built-in scheduler",
    )
    parser.add_argument(
        "--process-now",
        action="store_true",
        help="Immediately trigger Claude to process Needs_Action, then exit",
    )
    args = parser.parse_args()

    # Platinum: cloud role delegates entirely to cloud orchestrator
    if args.role == "cloud":
        try:
            from cloud.orchestrator_cloud import main as cloud_main
            cloud_main()
        except ImportError as err:
            logger.error(f"Cloud package not available: {err}")
            raise SystemExit(1)
        return

    if args.process_now:
        process_needs_action()
        return

    watcher_list = [w.strip() for w in args.watchers.split(",") if w.strip()]
    orch = Orchestrator(watchers=watcher_list, enable_scheduler=not args.no_scheduler)
    orch.start()
    orch.wait()


if __name__ == "__main__":
    main()
