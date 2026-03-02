"""
base_watcher.py — Abstract base class for all AI Employee watchers.

All watchers follow the same lifecycle:
  1. __init__  — configure paths and interval
  2. check_for_updates() — return a list of new items to process
  3. create_action_file() — write a .md file to /Needs_Action for each item
  4. run() — poll loop (blocking)
"""

import time
import logging
import json
from pathlib import Path
from abc import ABC, abstractmethod
from datetime import datetime, timezone


def _setup_logging(name: str) -> logging.Logger:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    return logging.getLogger(name)


class BaseWatcher(ABC):
    """
    Abstract base for all watchers.

    Subclasses must implement:
      - check_for_updates() -> list
      - create_action_file(item) -> Path
    """

    def __init__(self, vault_path: str, check_interval: int = 60, domain: str = ""):
        self.vault_path = Path(vault_path).resolve()
        self.domain = domain
        # When domain is set, write action files to the domain subfolder
        if domain:
            self.needs_action = self.vault_path / "Needs_Action" / domain
        else:
            self.needs_action = self.vault_path / "Needs_Action"
        self.done = self.vault_path / "Done"
        self.logs = self.vault_path / "Logs"
        self.check_interval = check_interval
        self.logger = _setup_logging(self.__class__.__name__)
        self._ensure_folders()

    # ------------------------------------------------------------------
    # Folder management
    # ------------------------------------------------------------------

    def _ensure_folders(self) -> None:
        """Create required vault folders if they don't exist."""
        for folder in (self.needs_action, self.done, self.logs):
            folder.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def check_for_updates(self) -> list:
        """Return a list of new items to process. Must be implemented by subclass."""

    @abstractmethod
    def create_action_file(self, item) -> Path:
        """Write a .md action file to Needs_Action. Must be implemented by subclass."""

    # ------------------------------------------------------------------
    # Audit logging
    # ------------------------------------------------------------------

    def log_action(self, action_type: str, target: str, result: str, details: dict = None) -> None:
        """Append a JSON log entry to /Logs/YYYY-MM-DD.json."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        log_file = self.logs / f"{today}.json"

        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action_type": action_type,
            "actor": self.__class__.__name__,
            "target": target,
            "result": result,
        }
        if details:
            entry["details"] = details

        # Read existing entries or start fresh
        entries = []
        if log_file.exists():
            try:
                entries = json.loads(log_file.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                entries = []

        entries.append(entry)
        log_file.write_text(json.dumps(entries, indent=2), encoding="utf-8")

    # ------------------------------------------------------------------
    # Run loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        """
        Blocking poll loop. Runs forever until interrupted (Ctrl+C).
        Checks for updates every self.check_interval seconds.
        """
        self.logger.info(
            f"Starting {self.__class__.__name__} "
            f"(vault={self.vault_path}, interval={self.check_interval}s)"
        )
        while True:
            try:
                items = self.check_for_updates()
                if items:
                    self.logger.info(f"Found {len(items)} new item(s)")
                for item in items:
                    try:
                        action_file = self.create_action_file(item)
                        self.logger.info(f"Created action file: {action_file.name}")
                        self.log_action(
                            action_type="action_file_created",
                            target=str(action_file),
                            result="success",
                        )
                    except Exception as item_err:
                        self.logger.error(f"Failed to create action file for {item}: {item_err}")
                        self.log_action(
                            action_type="action_file_created",
                            target=str(item),
                            result="error",
                            details={"error": str(item_err)},
                        )
            except KeyboardInterrupt:
                self.logger.info("Watcher stopped by user.")
                break
            except Exception as err:
                self.logger.error(f"Unexpected error in poll loop: {err}")
                self.log_action(
                    action_type="poll_error",
                    target="poll_loop",
                    result="error",
                    details={"error": str(err)},
                )
            time.sleep(self.check_interval)
