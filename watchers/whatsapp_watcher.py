"""
whatsapp_watcher.py — WhatsApp Web watcher via Playwright (Gold Tier).

Monitors WhatsApp Web for incoming messages containing trigger keywords
(urgent, invoice, payment, help, asap, etc.) and creates Needs_Action files.

Setup (one-time):
  1. Start Playwright MCP server:
       bash .claude/skills/browsing-with-playwright/scripts/start-server.sh
  2. Run with --login flag to authenticate WhatsApp Web:
       python -m watchers.whatsapp_watcher --login
  3. Scan QR code in the browser window that opens
  4. Session is saved — subsequent runs don't need re-login
  5. Run normally:
       python -m watchers.whatsapp_watcher

NOTE: WhatsApp Web automation is for personal productivity.
      Review WhatsApp's Terms of Service before use.

Environment variables (.env):
  VAULT_PATH              — path to vault
  WHATSAPP_CHECK_INTERVAL — seconds between checks (default: 30)
  WHATSAPP_KEYWORDS       — comma-separated trigger keywords
  PLAYWRIGHT_MCP_URL      — MCP server URL (default: http://localhost:8808)
  DRY_RUN                 — if "true", creates action files but marks dry_run
"""

import argparse
import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from watchers.base_watcher import BaseWatcher

load_dotenv()

DEFAULT_KEYWORDS = ["urgent", "asap", "invoice", "payment", "help", "important", "deadline"]
MCP_URL = os.getenv("PLAYWRIGHT_MCP_URL", "http://localhost:8808")
MCP_CLIENT = Path(".claude/skills/browsing-with-playwright/scripts/mcp-client.py")


# ──────────────────────────────────────────────────────────────────────
# Playwright MCP helper
# ──────────────────────────────────────────────────────────────────────

def _call_tool(tool: str, params: dict) -> dict:
    """Call a Playwright MCP tool via the bundled mcp-client.py."""
    result = subprocess.run(
        ["python3", str(MCP_CLIENT), "call", "-u", MCP_URL, "-t", tool, "-p", json.dumps(params)],
        capture_output=True, text=True, timeout=30
    )
    if result.stdout:
        try:
            return json.loads(result.stdout)
        except json.JSONDecodeError:
            return {"raw": result.stdout}
    return {}


def _is_mcp_running() -> bool:
    """Check if Playwright MCP server is running."""
    try:
        result = subprocess.run(
            ["python3", str(MCP_CLIENT), "list", "-u", MCP_URL],
            capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False


# ──────────────────────────────────────────────────────────────────────
# WhatsApp Watcher
# ──────────────────────────────────────────────────────────────────────

class WhatsAppWatcher(BaseWatcher):
    """
    Polls WhatsApp Web for unread messages containing trigger keywords.
    Uses Playwright MCP for browser automation — no native WhatsApp API needed.
    """

    def __init__(
        self,
        vault_path: str,
        check_interval: int = 30,
        keywords: list[str] = None,
        dry_run: bool = False,
    ):
        super().__init__(vault_path, check_interval=check_interval)
        self.keywords = keywords or DEFAULT_KEYWORDS
        self.dry_run = dry_run
        self._seen_messages: set[str] = set()

        if not MCP_CLIENT.exists():
            raise FileNotFoundError(
                f"Playwright MCP client not found at {MCP_CLIENT}\n"
                "Make sure browsing-with-playwright skill is installed."
            )

    def _navigate_to_whatsapp(self) -> bool:
        """Navigate to WhatsApp Web and wait for it to load."""
        _call_tool("browser_navigate", {"url": "https://web.whatsapp.com"})
        time.sleep(3)
        result = _call_tool("browser_wait_for", {"text": "Search or start new chat", "timeout": 15000})
        return bool(result)

    def _get_unread_chats(self) -> list[dict]:
        """Scrape unread chat list from WhatsApp Web."""
        snapshot = _call_tool("browser_snapshot", {})
        raw = snapshot.get("raw", "") or json.dumps(snapshot)

        unread_chats = []
        # Parse snapshot for unread indicators and message previews
        lines = raw.split("\n")
        current_chat = {}
        for line in lines:
            line_lower = line.lower()
            if any(kw in line_lower for kw in self.keywords):
                if current_chat:
                    unread_chats.append(current_chat)
                current_chat = {"preview": line.strip(), "keyword": next(
                    kw for kw in self.keywords if kw in line_lower
                )}
            elif "unread" in line_lower and current_chat:
                current_chat["unread"] = True
        if current_chat:
            unread_chats.append(current_chat)

        return unread_chats

    def check_for_updates(self) -> list:
        """Check WhatsApp Web for new keyword-triggered messages."""
        if not _is_mcp_running():
            self.logger.warning(
                "Playwright MCP not running. Start it: "
                "bash .claude/skills/browsing-with-playwright/scripts/start-server.sh"
            )
            return []

        try:
            if not self._navigate_to_whatsapp():
                self.logger.warning("WhatsApp Web not loaded — may need re-login (run --login)")
                return []

            chats = self._get_unread_chats()
            new_chats = []
            for chat in chats:
                msg_key = f"{chat.get('preview', '')[:50]}"
                if msg_key not in self._seen_messages:
                    new_chats.append(chat)
                    self._seen_messages.add(msg_key)

            return new_chats

        except Exception as err:
            self.logger.error(f"WhatsApp check error: {err}")
            return []

    def create_action_file(self, item: dict) -> Path:
        """Create a Needs_Action file for a WhatsApp message."""
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y%m%d_%H%M%S")
        filename = f"WHATSAPP_{ts}.md"
        filepath = self.needs_action / filename

        keyword = item.get("keyword", "unknown")
        preview = item.get("preview", "No preview available")
        dry_prefix = "[DRY RUN] " if self.dry_run else ""

        content = f"""---
type: whatsapp_message
received: {now.isoformat()}
keyword_trigger: {keyword}
priority: high
status: pending
dry_run: {str(self.dry_run).lower()}
---

## {dry_prefix}WhatsApp Message Received

A message containing the keyword **"{keyword}"** was detected.

| Field   | Value |
|---------|-------|
| Trigger | `{keyword}` |
| Received | {now.strftime("%Y-%m-%d %H:%M UTC")} |
| Priority | High |

## Message Preview

> {preview}

## Suggested Actions

- [ ] Open WhatsApp Web and read the full message
- [ ] Determine if response is needed
- [ ] Draft reply (requires human approval — Handbook §3)
- [ ] If invoice/payment related, create approval file
- [ ] Archive after processing

## Notes

_Add context before passing to Claude._
"""
        filepath.write_text(content, encoding="utf-8")
        return filepath


# ──────────────────────────────────────────────────────────────────────
# Login helper
# ──────────────────────────────────────────────────────────────────────

def login_whatsapp() -> None:
    """Open WhatsApp Web for QR code scanning — one-time login."""
    if not _is_mcp_running():
        print("ERROR: Playwright MCP not running.")
        print("Start it first: bash .claude/skills/browsing-with-playwright/scripts/start-server.sh")
        raise SystemExit(1)

    print("Opening WhatsApp Web for QR scan...")
    _call_tool("browser_navigate", {"url": "https://web.whatsapp.com"})
    print("Scan the QR code in the browser window.")
    print("Press Enter here when done (after chats load)...")
    input()
    print("WhatsApp session saved. Run watcher without --login now.")


# ──────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="AI Employee — WhatsApp Watcher (Gold Tier)")
    parser.add_argument("--vault", default=os.getenv("VAULT_PATH", "AI_Employee_Vault"))
    parser.add_argument("--interval", type=int,
                        default=int(os.getenv("WHATSAPP_CHECK_INTERVAL", "30")))
    parser.add_argument("--keywords",
                        default=os.getenv("WHATSAPP_KEYWORDS", ",".join(DEFAULT_KEYWORDS)))
    parser.add_argument("--login", action="store_true", help="Open browser for WhatsApp QR login")
    parser.add_argument("--dry-run", action="store_true",
                        default=os.getenv("DRY_RUN", "true").lower() == "true")
    args = parser.parse_args()

    if args.login:
        login_whatsapp()
        return

    vault = Path(args.vault).resolve()
    if not vault.exists():
        print(f"ERROR: Vault not found: {vault}")
        raise SystemExit(1)

    keywords = [k.strip() for k in args.keywords.split(",") if k.strip()]
    watcher = WhatsAppWatcher(
        vault_path=str(vault),
        check_interval=args.interval,
        keywords=keywords,
        dry_run=args.dry_run,
    )
    watcher.run()


if __name__ == "__main__":
    main()
