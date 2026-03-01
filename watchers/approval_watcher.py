"""
approval_watcher.py — Human-in-the-Loop (HITL) workflow watcher (Silver Tier).

Monitors two vault folders:
  /Pending_Approval — new approval-request files appear here (created by Claude)
  /Approved         — human moves a file here to approve the action
  /Rejected         — human moves a file here to reject

On file in /Approved:
  - Reads the approval file to determine action type
  - Dispatches the action: send_email or post_linkedin
  - Moves file to /Done and logs the result

On file in /Pending_Approval:
  - Alerts the user (console notification)
  - Logs the event

Usage:
  python -m watchers.approval_watcher

Environment variables (.env):
  VAULT_PATH        — path to vault
  SMTP_HOST         — SMTP server (default: smtp.gmail.com)
  SMTP_PORT         — SMTP port (default: 587)
  SMTP_USER         — sender email address
  SMTP_PASSWORD     — app password (NOT your main Gmail password)
  DRY_RUN           — if "true", logs actions without executing
"""

import json
import os
import shutil
import smtplib
import time
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import yaml
from dotenv import load_dotenv
from watchdog.events import FileCreatedEvent, FileSystemEventHandler
from watchdog.observers import Observer

from watchers.base_watcher import BaseWatcher

load_dotenv()


# ──────────────────────────────────────────────────────────────────────
# YAML frontmatter parser
# ──────────────────────────────────────────────────────────────────────

def parse_frontmatter(text: str) -> tuple[dict, str]:
    """Extract YAML frontmatter from a markdown file. Returns (metadata, body)."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    try:
        meta = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        meta = {}
    return meta, parts[2].strip()


# ──────────────────────────────────────────────────────────────────────
# Action dispatchers
# ──────────────────────────────────────────────────────────────────────

def _dispatch_send_email(meta: dict, body: str, dry_run: bool) -> str:
    """Send an email using SMTP credentials from environment."""
    to = meta.get("to", meta.get("target", ""))
    subject = meta.get("subject", "(no subject)")
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASSWORD", "")

    if not smtp_user or not smtp_pass:
        return "ERROR: SMTP_USER or SMTP_PASSWORD not set in .env"

    if dry_run:
        return f"[DRY RUN] Would send email to {to!r} | subject: {subject!r}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = to
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.ehlo()
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, [to], msg.as_string())

    return f"Email sent to {to!r} | subject: {subject!r}"


def _dispatch_post_linkedin(meta: dict, body: str, dry_run: bool) -> str:
    """Post to LinkedIn via the Playwright MCP client."""
    if dry_run:
        return f"[DRY RUN] Would post to LinkedIn: {body[:80]}..."

    try:
        # Use the playwright MCP client bundled with the browsing skill
        import subprocess, json as _json
        mcp_client = Path(".claude/skills/browsing-with-playwright/scripts/mcp-client.py")
        if not mcp_client.exists():
            return "ERROR: Playwright MCP client not found at expected path"

        base_url = "http://localhost:8808"

        def call_tool(tool: str, params: dict) -> dict:
            result = subprocess.run(
                ["python3", str(mcp_client), "call", "-u", base_url, "-t", tool, "-p", _json.dumps(params)],
                capture_output=True, text=True, timeout=30
            )
            return _json.loads(result.stdout) if result.stdout else {}

        call_tool("browser_navigate", {"url": "https://www.linkedin.com/feed/"})
        time.sleep(2)

        # Click "Start a post"
        call_tool("browser_click", {"element": "Start a post button", "ref": ""})
        time.sleep(1)

        # Type post content
        call_tool("browser_type", {"element": "post text area", "ref": "", "text": body[:3000]})
        time.sleep(1)

        # Click Post button
        call_tool("browser_click", {"element": "Post button", "ref": ""})
        time.sleep(2)

        return "LinkedIn post submitted via Playwright"
    except Exception as err:
        return f"ERROR posting to LinkedIn: {err}"


# ──────────────────────────────────────────────────────────────────────
# Watchdog event handlers
# ──────────────────────────────────────────────────────────────────────

class _PendingApprovalHandler(FileSystemEventHandler):
    def __init__(self, watcher: "ApprovalWatcher"):
        super().__init__()
        self._w = watcher

    def on_created(self, event: FileCreatedEvent) -> None:
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.name.startswith("."):
            return
        self._w.logger.info(f"ACTION REQUIRED: New approval request → {path.name}")
        self._w.logger.info(f"  Review: {path}")
        self._w.logger.info(f"  Approve: move to /Approved/   |   Reject: move to /Rejected/")
        self._w.log_action("approval_requested", str(path), "pending")


class _ApprovedHandler(FileSystemEventHandler):
    def __init__(self, watcher: "ApprovalWatcher"):
        super().__init__()
        self._w = watcher

    def on_created(self, event: FileCreatedEvent) -> None:
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.name.startswith("."):
            return
        self._w.logger.info(f"Approval detected: {path.name} — dispatching action...")
        self._w._dispatch(path)


class _RejectedHandler(FileSystemEventHandler):
    def __init__(self, watcher: "ApprovalWatcher"):
        super().__init__()
        self._w = watcher

    def on_created(self, event: FileCreatedEvent) -> None:
        if event.is_directory:
            return
        path = Path(event.src_path)
        if path.name.startswith("."):
            return
        self._w.logger.info(f"Rejected: {path.name} — moving to Done")
        dest = self._w.done / path.name
        shutil.move(str(path), str(dest))
        self._w.log_action("action_rejected", path.name, "rejected")


# ──────────────────────────────────────────────────────────────────────
# ApprovalWatcher
# ──────────────────────────────────────────────────────────────────────

class ApprovalWatcher(BaseWatcher):
    """
    Watches /Pending_Approval, /Approved, and /Rejected for HITL workflow.

    Supported action types in approval file frontmatter:
      action: send_email
      action: post_linkedin
    """

    def __init__(self, vault_path: str, dry_run: bool = False):
        super().__init__(vault_path, check_interval=5)
        self.pending_approval = self.vault_path / "Pending_Approval"
        self.approved = self.vault_path / "Approved"
        self.rejected = self.vault_path / "Rejected"
        self.dry_run = dry_run

        for folder in (self.pending_approval, self.approved, self.rejected):
            folder.mkdir(parents=True, exist_ok=True)

        if dry_run:
            self.logger.info("[DRY RUN] Mode active — actions logged but not executed")

    # ------------------------------------------------------------------
    # BaseWatcher interface (unused — event-driven via watchdog)
    # ------------------------------------------------------------------

    def check_for_updates(self) -> list:
        return []

    def create_action_file(self, item) -> Path:
        raise NotImplementedError("ApprovalWatcher does not create action files")

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def _dispatch(self, approved_file: Path) -> None:
        """Read an approved file and execute the requested action."""
        try:
            text = approved_file.read_text(encoding="utf-8")
            meta, body = parse_frontmatter(text)
            action = meta.get("action", "").lower()

            if action == "send_email":
                result = _dispatch_send_email(meta, body, self.dry_run)
            elif action == "post_linkedin":
                result = _dispatch_post_linkedin(meta, body, self.dry_run)
            else:
                result = f"Unknown action type: {action!r} — no handler registered"

            self.logger.info(f"Dispatch result: {result}")
            self.log_action(
                action_type=f"action_executed:{action}",
                target=approved_file.name,
                result="success" if "ERROR" not in result else "error",
                details={"result": result, "dry_run": self.dry_run},
            )

        except Exception as err:
            self.logger.error(f"Dispatch error for {approved_file.name}: {err}")
            self.log_action("dispatch_error", approved_file.name, "error", {"error": str(err)})
        finally:
            # Always move to Done (even on error — so it doesn't loop)
            dest = self.done / approved_file.name
            if approved_file.exists():
                shutil.move(str(approved_file), str(dest))
                self.logger.info(f"Moved to Done: {approved_file.name}")

    # ------------------------------------------------------------------
    # Run (event-driven, overrides base)
    # ------------------------------------------------------------------

    def run(self) -> None:
        self.logger.info(f"Approval Watcher starting — vault: {self.vault_path}")
        self.logger.info(f"  Watching: Pending_Approval/ | Approved/ | Rejected/")
        self.logger.info("Press Ctrl+C to stop.\n")

        observer = Observer()
        observer.schedule(_PendingApprovalHandler(self), str(self.pending_approval), recursive=False)
        observer.schedule(_ApprovedHandler(self), str(self.approved), recursive=False)
        observer.schedule(_RejectedHandler(self), str(self.rejected), recursive=False)
        observer.start()

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.logger.info("Stopping Approval Watcher...")
        finally:
            observer.stop()
            observer.join()


# ──────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="AI Employee — Approval Watcher (HITL)")
    parser.add_argument("--vault", default=os.getenv("VAULT_PATH", "AI_Employee_Vault"))
    parser.add_argument("--dry-run", action="store_true",
                        default=os.getenv("DRY_RUN", "true").lower() == "true")
    args = parser.parse_args()

    vault = Path(args.vault).resolve()
    if not vault.exists():
        print(f"ERROR: Vault not found: {vault}")
        raise SystemExit(1)

    ApprovalWatcher(str(vault), dry_run=args.dry_run).run()


if __name__ == "__main__":
    main()
