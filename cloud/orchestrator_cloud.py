"""
orchestrator_cloud.py — Cloud agent entry point (Platinum Tier).

Cloud agent runs on Ubuntu VM (24/7). It is draft-only — it never sends
emails, never touches WhatsApp, and never executes payments.

Responsibilities:
  1. GmailWatcher (domain="cloud") → writes Needs_Action/cloud/
  2. FilesystemWatcher (domain="cloud") → watches Needs_Action/cloud/
  3. ClaimManager processes action files → drafts → Pending_Approval/cloud/
  4. HealthMonitor thread → Signals/health_cloud.json
  5. VaultSync thread → git push cloud-owned paths every SYNC_INTERVAL seconds
  6. Trigger Claude Code (--print) for reasoning on claimed items

Forbidden:
  - WhatsApp watcher (no Playwright on cloud)
  - Sending emails (no smtp_send MCP call)
  - Payment / banking actions
  - Writing Dashboard.md

Usage:
  AGENT_ROLE=cloud python cloud/orchestrator_cloud.py
  AGENT_ROLE=cloud DRY_RUN=true python cloud/orchestrator_cloud.py --no-scheduler
  AGENT_ROLE=cloud python cloud/orchestrator_cloud.py --watchers gmail,fs

Environment variables:
  VAULT_PATH              — path to vault (default: AI_Employee_Vault)
  DRY_RUN                 — if "true", log actions without executing
  ENABLE_GMAIL            — if "true", start Gmail watcher
  SYNC_INTERVAL           — seconds between git push cycles (default: 60)
  HEALTH_CHECK_INTERVAL   — seconds between health checks (default: 30)
  DOMAIN                  — domain subfolder name (default: cloud)
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
logger = logging.getLogger("cloud.orchestrator")

VAULT_PATH = Path(os.getenv("VAULT_PATH", "AI_Employee_Vault")).resolve()
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"
ENABLE_GMAIL = os.getenv("ENABLE_GMAIL", "false").lower() == "true"
DOMAIN = os.getenv("DOMAIN", "cloud")
SYNC_INTERVAL = int(os.getenv("SYNC_INTERVAL", "60"))
HEALTH_CHECK_INTERVAL = int(os.getenv("HEALTH_CHECK_INTERVAL", "30"))


# ──────────────────────────────────────────────────────────────────────
# Supervised thread (mirrors orchestrator.py WatcherThread)
# ──────────────────────────────────────────────────────────────────────

class SupervisedThread(threading.Thread):
    RESTART_DELAY = 10

    def __init__(self, name: str, factory, *args, **kwargs):
        super().__init__(name=name, daemon=True)
        self._factory = factory
        self._args = args
        self._kwargs = kwargs
        self._stop_event = threading.Event()
        self.logger = logging.getLogger(f"cloud.{name}")

    def run(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.logger.info(f"Starting {self.name}")
                obj = self._factory(*self._args, **self._kwargs)
                obj.run()
            except Exception as err:
                self.logger.error(f"{self.name} crashed: {err}")
            if not self._stop_event.is_set():
                self.logger.warning(
                    f"{self.name} stopped. Restarting in {self.RESTART_DELAY}s..."
                )
                time.sleep(self.RESTART_DELAY)

    def stop(self) -> None:
        self._stop_event.set()


# ──────────────────────────────────────────────────────────────────────
# Claude Code trigger (cloud-specific prompt)
# ──────────────────────────────────────────────────────────────────────

def trigger_claude_cloud(item_path: Path) -> str:
    """
    Invoke Claude Code to draft a reply for a claimed action file.
    Draft result goes to Pending_Approval/cloud/ — never sent directly.
    """
    if DRY_RUN:
        logger.info(f"[DRY_RUN] Would invoke Claude for: {item_path.name}")
        return "[DRY_RUN] Claude not invoked"

    prompt = (
        f"You are the AI Employee Cloud Agent. Vault is at: {VAULT_PATH}\n\n"
        f"IMPORTANT RULES (Platinum Cloud Agent):\n"
        f"  1. Read Company_Handbook.md before acting.\n"
        f"  2. You are DRAFT-ONLY. Never send emails. Never post to social media.\n"
        f"  3. Never access WhatsApp, banking, or payments.\n"
        f"  4. Never write to Dashboard.md directly.\n"
        f"  5. Write drafts to Pending_Approval/cloud/ for human approval.\n"
        f"  6. Write update fragments to Updates/ (not Dashboard.md).\n\n"
        f"Action item to process: {item_path}\n\n"
        f"Steps:\n"
        f"  1. Read the action file.\n"
        f"  2. Create Plan_<name>.md in Plans/cloud/.\n"
        f"  3. Draft a reply/response in Pending_Approval/cloud/.\n"
        f"  4. Move the action file to Done/.\n"
        f"  5. Write a brief update fragment to Updates/UPDATE_<name>.md.\n"
    )
    try:
        result = subprocess.run(
            ["claude", "--print", prompt],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(VAULT_PATH.parent),
        )
        if result.returncode != 0:
            return f"Claude error (code {result.returncode}): {result.stderr[:500]}"
        return result.stdout
    except FileNotFoundError:
        return "ERROR: 'claude' command not found"
    except subprocess.TimeoutExpired:
        return "ERROR: Claude Code timed out"
    except Exception as err:
        return f"ERROR: {err}"


# ──────────────────────────────────────────────────────────────────────
# Cloud claim-process loop (watcher-style runnable)
# ──────────────────────────────────────────────────────────────────────

class CloudActionProcessor:
    """
    Polls Needs_Action/cloud/ for new items, claims them, and triggers Claude.
    This is a lightweight alternative to a full FilesystemWatcher for the cloud.
    """

    def __init__(self, vault_path: Path = VAULT_PATH, interval: int = 30):
        self.vault_path = vault_path
        self.interval = interval
        self._stop = threading.Event()
        self.logger = logging.getLogger("cloud.ActionProcessor")

        from cloud.claim_manager import ClaimManager
        self.claim_mgr = ClaimManager(
            source=vault_path / "Needs_Action" / DOMAIN,
            destination=vault_path / "In_Progress" / DOMAIN,
        )
        self.done_dir = vault_path / "Done"

    def run(self) -> None:
        self.logger.info(f"CloudActionProcessor starting (domain={DOMAIN})")
        while not self._stop.is_set():
            try:
                item = self.claim_mgr.claim_next()
                if item:
                    self.logger.info(f"Processing: {item.name}")
                    output = trigger_claude_cloud(item)
                    self.logger.info(f"Claude output (first 500): {output[:500]}")
                    self.claim_mgr.release(item, self.done_dir)
            except Exception as err:
                self.logger.error(f"ActionProcessor error: {err}")
            self._stop.wait(self.interval)

    def stop(self) -> None:
        self._stop.set()


# ──────────────────────────────────────────────────────────────────────
# Cloud Orchestrator
# ──────────────────────────────────────────────────────────────────────

class CloudOrchestrator:
    """Manages cloud agent threads: Gmail, ActionProcessor, HealthMonitor, VaultSync."""

    def __init__(self, watchers: list[str], enable_scheduler: bool = False):
        self._threads: list[SupervisedThread] = []
        self.watchers = watchers
        self.enable_scheduler = enable_scheduler

    def _build_threads(self) -> None:
        # Always run action processor
        self._threads.append(
            SupervisedThread(
                "CloudActionProcessor",
                CloudActionProcessor,
                VAULT_PATH,
            )
        )

        # Gmail watcher (cloud domain)
        if ENABLE_GMAIL or "gmail" in self.watchers:
            try:
                from watchers.gmail_watcher import GmailWatcher
                self._threads.append(
                    SupervisedThread(
                        "GmailWatcher[cloud]",
                        GmailWatcher,
                        vault_path=str(VAULT_PATH),
                        credentials_path=os.getenv(
                            "GMAIL_CREDENTIALS_PATH",
                            "credentials/gmail_credentials.json",
                        ),
                        token_path=os.getenv(
                            "GMAIL_TOKEN_PATH", "credentials/gmail_token.json"
                        ),
                        dry_run=DRY_RUN,
                        domain=DOMAIN,
                    )
                )
            except Exception as err:
                logger.warning(f"Gmail watcher unavailable: {err}")

        # Filesystem watcher (cloud domain only)
        if "fs" in self.watchers:
            try:
                from watchers.filesystem_watcher import FilesystemWatcher
                self._threads.append(
                    SupervisedThread(
                        "FilesystemWatcher[cloud]",
                        FilesystemWatcher,
                        str(VAULT_PATH),
                        domain=DOMAIN,
                    )
                )
            except Exception as err:
                logger.warning(f"FilesystemWatcher unavailable: {err}")

        # Health monitor
        from cloud.health_monitor import HealthMonitor
        self._threads.append(
            SupervisedThread(
                "HealthMonitor",
                HealthMonitor,
                HEALTH_CHECK_INTERVAL,
            )
        )

        # Vault sync (cloud push)
        from sync.vault_sync import VaultSync
        self._threads.append(
            SupervisedThread(
                "VaultSync[cloud]",
                VaultSync,
                role="cloud",
                interval=SYNC_INTERVAL,
            )
        )

    def start(self) -> None:
        if not VAULT_PATH.exists():
            logger.error(f"Vault not found: {VAULT_PATH}")
            raise SystemExit(1)

        logger.info("Cloud Agent Orchestrator starting (Platinum Tier)")
        logger.info(f"  Vault:    {VAULT_PATH}")
        logger.info(f"  Domain:   {DOMAIN}")
        logger.info(f"  Dry run:  {DRY_RUN}")

        self._build_threads()

        for t in self._threads:
            t.start()
            logger.info(f"  Started: {t.name}")

        logger.info("Cloud Orchestrator running. Press Ctrl+C to stop.\n")

    def wait(self) -> None:
        try:
            while True:
                time.sleep(5)
        except KeyboardInterrupt:
            self.stop()

    def stop(self) -> None:
        logger.info("Stopping cloud agent threads...")
        for t in self._threads:
            t.stop()
        logger.info("Cloud Orchestrator stopped.")


# ──────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="AI Employee — Cloud Agent (Platinum Tier, draft-only)"
    )
    parser.add_argument(
        "--watchers",
        default="gmail,fs",
        help="Comma-separated watcher names for cloud: gmail, fs (default: gmail,fs)",
    )
    parser.add_argument(
        "--no-scheduler",
        action="store_true",
        help="Disable scheduler (always true for cloud — scheduler runs on local)",
    )
    args = parser.parse_args()

    watcher_list = [w.strip() for w in args.watchers.split(",") if w.strip()]
    orch = CloudOrchestrator(watchers=watcher_list, enable_scheduler=False)
    orch.start()
    orch.wait()


if __name__ == "__main__":
    main()
