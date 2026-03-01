"""
gmail_watcher.py — Monitors Gmail for unread important emails (Silver Tier).

One-time setup:
  1. Go to console.cloud.google.com → New project → Enable Gmail API
  2. Create OAuth 2.0 credentials (Desktop app type)
  3. Download as: credentials/gmail_credentials.json
  4. Run: python -m watchers.gmail_watcher --auth   (opens browser consent screen)
  5. Token saved to: credentials/gmail_token.json
  6. Run normally: python -m watchers.gmail_watcher

Environment variables (.env):
  VAULT_PATH               — path to vault (default: AI_Employee_Vault)
  GMAIL_CREDENTIALS_PATH   — default: credentials/gmail_credentials.json
  GMAIL_TOKEN_PATH         — default: credentials/gmail_token.json
  GMAIL_CHECK_INTERVAL     — seconds between polls (default: 120)
  GMAIL_QUERY              — Gmail search query (default: is:unread is:important)
  DRY_RUN                  — if "true", creates action files but logs [DRY RUN]
"""

import argparse
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

from watchers.base_watcher import BaseWatcher

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
DEFAULT_QUERY = "is:unread is:important"


class GmailWatcher(BaseWatcher):
    """
    Polls Gmail for unread important emails and creates Needs_Action .md files.

    Each detected email becomes a FILE_EMAIL_<id>.md in /Needs_Action with
    full metadata and a suggested-actions checklist for Claude to process.
    """

    def __init__(
        self,
        vault_path: str,
        credentials_path: str = "credentials/gmail_credentials.json",
        token_path: str = "credentials/gmail_token.json",
        check_interval: int = 120,
        query: str = DEFAULT_QUERY,
        dry_run: bool = False,
    ):
        super().__init__(vault_path, check_interval=check_interval)
        self.credentials_path = Path(credentials_path)
        self.token_path = Path(token_path)
        self.query = query
        self.dry_run = dry_run
        self._processed_ids: set[str] = set()
        self._service = None

        if dry_run:
            self.logger.info("[DRY RUN] Mode active — action files will be created but no real changes made")

    # ------------------------------------------------------------------
    # Gmail API
    # ------------------------------------------------------------------

    def _get_service(self):
        """Build and return an authenticated Gmail API service object."""
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from google_auth_oauthlib.flow import InstalledAppFlow
            from googleapiclient.discovery import build
        except ImportError:
            raise RuntimeError(
                "Google API packages not installed. Run:\n"
                "  pip install google-auth google-auth-oauthlib google-api-python-client"
            )

        creds = None
        if self.token_path.exists():
            from google.oauth2.credentials import Credentials
            creds = Credentials.from_authorized_user_file(str(self.token_path), SCOPES)

        if not creds or not creds.valid:
            from google.auth.transport.requests import Request
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                if not self.credentials_path.exists():
                    raise FileNotFoundError(
                        f"Gmail credentials not found at: {self.credentials_path}\n"
                        "Run with --auth flag first to set up OAuth."
                    )
                from google_auth_oauthlib.flow import InstalledAppFlow
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self.credentials_path), SCOPES
                )
                creds = flow.run_local_server(port=0)

            self.token_path.parent.mkdir(parents=True, exist_ok=True)
            self.token_path.write_text(creds.to_json(), encoding="utf-8")
            self.logger.info(f"Token saved to {self.token_path}")

        from googleapiclient.discovery import build
        return build("gmail", "v1", credentials=creds)

    # ------------------------------------------------------------------
    # BaseWatcher interface
    # ------------------------------------------------------------------

    def check_for_updates(self) -> list:
        """Query Gmail for new unread important messages not yet processed."""
        try:
            if self._service is None:
                self._service = self._get_service()

            results = (
                self._service.users()
                .messages()
                .list(userId="me", q=self.query, maxResults=20)
                .execute()
            )
            messages = results.get("messages", [])
            new = [m for m in messages if m["id"] not in self._processed_ids]
            if new:
                self.logger.info(f"Gmail: {len(new)} new message(s) found")
            return new

        except Exception as err:
            self.logger.error(f"Gmail API error: {err}")
            self._service = None  # force re-auth on next cycle
            return []

    def create_action_file(self, message: dict) -> Path:
        """Fetch message metadata and write a structured .md action file."""
        msg = (
            self._service.users()
            .messages()
            .get(
                userId="me",
                id=message["id"],
                format="metadata",
                metadataHeaders=["From", "Subject", "Date", "To"],
            )
            .execute()
        )

        headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
        snippet = msg.get("snippet", "").replace("`", "'")
        now = datetime.now(timezone.utc)
        msg_id = message["id"]

        prefix = "[DRY RUN] " if self.dry_run else ""
        content = f"""---
type: email
message_id: {msg_id}
from: "{headers.get('From', 'Unknown')}"
to: "{headers.get('To', '')}"
subject: "{headers.get('Subject', 'No Subject')}"
date: "{headers.get('Date', '')}"
received: {now.isoformat()}
priority: high
status: pending
dry_run: {str(self.dry_run).lower()}
---

## {prefix}Email Received

| Field   | Value |
|---------|-------|
| From    | {headers.get('From', 'Unknown')} |
| To      | {headers.get('To', '')} |
| Subject | {headers.get('Subject', '(none)')} |
| Date    | {headers.get('Date', '')} |

## Preview

> {snippet}

## Suggested Actions

- [ ] Read the full email in Gmail
- [ ] Draft a reply (requires human approval — Handbook §3)
- [ ] Forward to relevant party (requires approval)
- [ ] Archive / mark as read after processing

## Notes

_Add any context here before passing to Claude._
"""
        filename = f"EMAIL_{msg_id}.md"
        filepath = self.needs_action / filename

        if not self.dry_run:
            filepath.write_text(content, encoding="utf-8")
        else:
            self.logger.info(f"[DRY RUN] Would write: {filepath.name}")
            filepath.write_text(content, encoding="utf-8")  # still write in dry-run for visibility

        self._processed_ids.add(msg_id)
        return filepath


# ------------------------------------------------------------------
# Auth helper
# ------------------------------------------------------------------

def authenticate(credentials_path: str, token_path: str) -> None:
    """Interactive one-time OAuth2 flow. Opens browser for consent."""
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("ERROR: Run: pip install google-auth-oauthlib")
        raise SystemExit(1)

    if not Path(credentials_path).exists():
        print(f"ERROR: credentials file not found at: {credentials_path}")
        print("Download it from Google Cloud Console → APIs & Services → Credentials")
        raise SystemExit(1)

    print(f"Opening browser for Google OAuth consent...")
    flow = InstalledAppFlow.from_client_secrets_file(credentials_path, SCOPES)
    creds = flow.run_local_server(port=0)

    Path(token_path).parent.mkdir(parents=True, exist_ok=True)
    Path(token_path).write_text(creds.to_json(), encoding="utf-8")
    print(f"Authentication successful. Token saved to: {token_path}")
    print("You can now run the watcher without --auth.")


# ------------------------------------------------------------------
# CLI entry point
# ------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="AI Employee — Gmail Watcher (Silver Tier)"
    )
    parser.add_argument(
        "--vault",
        default=os.getenv("VAULT_PATH", "AI_Employee_Vault"),
        help="Path to the Obsidian vault",
    )
    parser.add_argument(
        "--credentials",
        default=os.getenv("GMAIL_CREDENTIALS_PATH", "credentials/gmail_credentials.json"),
    )
    parser.add_argument(
        "--token",
        default=os.getenv("GMAIL_TOKEN_PATH", "credentials/gmail_token.json"),
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=int(os.getenv("GMAIL_CHECK_INTERVAL", "120")),
        help="Seconds between Gmail polls (default: 120)",
    )
    parser.add_argument(
        "--query",
        default=os.getenv("GMAIL_QUERY", DEFAULT_QUERY),
        help=f'Gmail search query (default: "{DEFAULT_QUERY}")',
    )
    parser.add_argument(
        "--auth",
        action="store_true",
        help="Run interactive OAuth2 setup (one-time)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=os.getenv("DRY_RUN", "true").lower() == "true",
    )
    args = parser.parse_args()

    if args.auth:
        authenticate(args.credentials, args.token)
        return

    vault = Path(args.vault).resolve()
    if not vault.exists():
        print(f"ERROR: Vault not found: {vault}")
        raise SystemExit(1)

    watcher = GmailWatcher(
        vault_path=str(vault),
        credentials_path=args.credentials,
        token_path=args.token,
        check_interval=args.interval,
        query=args.query,
        dry_run=args.dry_run,
    )
    watcher.run()


if __name__ == "__main__":
    main()
