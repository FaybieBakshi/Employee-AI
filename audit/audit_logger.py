"""
audit_logger.py — Comprehensive structured audit logging (Gold Tier).

Provides a centralized AuditLogger that writes JSON entries to:
  AI_Employee_Vault/Logs/YYYY-MM-DD.json

Every entry includes:
  timestamp, action_type, actor, target, result,
  domain (personal|business|system), tier, session_id, details

Also supports:
  - Log rotation (keeps last 90 days)
  - Daily summary generation
  - Log querying by date range / action type
"""

import json
import os
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

LOG_RETENTION_DAYS = 90
SESSION_ID = str(uuid.uuid4())[:8]


class AuditLogger:
    """
    Centralized audit logger for all AI Employee actions.
    Thread-safe append-to-JSON-array pattern.
    """

    def __init__(self, vault_path: str = None):
        self.vault_path = Path(vault_path or os.getenv("VAULT_PATH", "AI_Employee_Vault")).resolve()
        self.logs_dir = self.vault_path / "Logs"
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self.session_id = SESSION_ID

    # ------------------------------------------------------------------
    # Core logging
    # ------------------------------------------------------------------

    def log(
        self,
        action_type: str,
        target: str,
        result: str,
        actor: str = "claude_code",
        domain: str = "system",
        details: Optional[dict] = None,
        approval_status: str = "auto",
    ) -> dict:
        """
        Write a structured audit log entry.

        Args:
            action_type: e.g. "email_sent", "linkedin_posted", "invoice_created"
            target: what was acted on (filename, email, URL, etc.)
            result: "success", "error", "dry_run", "pending_approval"
            actor: who/what triggered the action
            domain: "personal" | "business" | "system"
            details: optional extra data dict
            approval_status: "auto" | "approved" | "rejected" | "pending"
        """
        now = datetime.now(timezone.utc)
        entry = {
            "timestamp": now.isoformat(),
            "session_id": self.session_id,
            "action_type": action_type,
            "actor": actor,
            "target": target,
            "result": result,
            "domain": domain,
            "approval_status": approval_status,
        }
        if details:
            entry["details"] = details

        log_file = self.logs_dir / now.strftime("%Y-%m-%d.json")
        self._append(log_file, entry)
        self._rotate_old_logs()
        return entry

    def _append(self, log_file: Path, entry: dict) -> None:
        entries = []
        if log_file.exists():
            try:
                entries = json.loads(log_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                entries = []
        entries.append(entry)
        log_file.write_text(json.dumps(entries, indent=2), encoding="utf-8")

    def _rotate_old_logs(self) -> None:
        """Delete log files older than LOG_RETENTION_DAYS."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=LOG_RETENTION_DAYS)
        for log_file in self.logs_dir.glob("*.json"):
            try:
                file_date = datetime.strptime(log_file.stem, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                if file_date < cutoff:
                    log_file.unlink()
            except ValueError:
                pass

    # ------------------------------------------------------------------
    # Domain-specific shortcuts
    # ------------------------------------------------------------------

    def log_personal(self, action_type: str, target: str, result: str, **kwargs) -> dict:
        return self.log(action_type, target, result, domain="personal", **kwargs)

    def log_business(self, action_type: str, target: str, result: str, **kwargs) -> dict:
        return self.log(action_type, target, result, domain="business", **kwargs)

    def log_error(self, action_type: str, target: str, error: str, domain: str = "system") -> dict:
        return self.log(action_type, target, "error", domain=domain, details={"error": error})

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def get_entries(self, date_str: str = None, action_type: str = None, domain: str = None) -> list[dict]:
        """
        Read log entries for a given date (default: today).
        Optionally filter by action_type or domain.
        """
        if date_str is None:
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        log_file = self.logs_dir / f"{date_str}.json"
        if not log_file.exists():
            return []

        try:
            entries = json.loads(log_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

        if action_type:
            entries = [e for e in entries if e.get("action_type") == action_type]
        if domain:
            entries = [e for e in entries if e.get("domain") == domain]

        return entries

    def get_weekly_entries(self) -> list[dict]:
        """Return all log entries from the last 7 days."""
        all_entries = []
        for i in range(7):
            date = datetime.now(timezone.utc) - timedelta(days=i)
            date_str = date.strftime("%Y-%m-%d")
            all_entries.extend(self.get_entries(date_str))
        return sorted(all_entries, key=lambda e: e.get("timestamp", ""), reverse=True)

    def daily_summary(self, date_str: str = None) -> dict:
        """Generate a summary of today's (or given date's) log entries."""
        entries = self.get_entries(date_str)
        by_type: dict[str, int] = {}
        by_domain: dict[str, int] = {}
        errors = 0

        for e in entries:
            by_type[e.get("action_type", "unknown")] = by_type.get(e.get("action_type", "unknown"), 0) + 1
            by_domain[e.get("domain", "system")] = by_domain.get(e.get("domain", "system"), 0) + 1
            if e.get("result") == "error":
                errors += 1

        return {
            "date": date_str or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "total_actions": len(entries),
            "errors": errors,
            "by_action_type": by_type,
            "by_domain": by_domain,
        }


# Module-level default logger (convenience)
_default_logger: AuditLogger | None = None


def get_logger(vault_path: str = None) -> AuditLogger:
    """Get or create the default AuditLogger instance."""
    global _default_logger
    if _default_logger is None:
        _default_logger = AuditLogger(vault_path)
    return _default_logger
