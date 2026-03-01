"""
filesystem_watcher.py — Monitors the vault's /Inbox folder for new files.

When a file is dropped into AI_Employee_Vault/Inbox/, this watcher:
  1. Detects the new file via watchdog's filesystem events
  2. Creates a FILE_<name>.md action file in /Needs_Action/
  3. Logs the action to /Logs/YYYY-MM-DD.json

Usage:
    python -m watchers.filesystem_watcher
  or:
    python watchers/filesystem_watcher.py

Set VAULT_PATH in .env or pass it as CLI arg:
    python watchers/filesystem_watcher.py --vault /path/to/AI_Employee_Vault
"""

import argparse
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from watchdog.events import FileSystemEventHandler, FileCreatedEvent
from watchdog.observers import Observer

from watchers.base_watcher import BaseWatcher

load_dotenv()

# ──────────────────────────────────────────────────────────────────────
# Event Handler (called by watchdog on file system events)
# ──────────────────────────────────────────────────────────────────────

class _InboxHandler(FileSystemEventHandler):
    """Watchdog handler that delegates to FilesystemWatcher on new files."""

    def __init__(self, watcher: "FilesystemWatcher"):
        super().__init__()
        self._watcher = watcher

    def on_created(self, event: FileCreatedEvent) -> None:
        if event.is_directory:
            return
        source = Path(event.src_path)
        # Ignore hidden files and .gitkeep
        if source.name.startswith("."):
            return
        self._watcher.logger.info(f"New file detected in Inbox: {source.name}")
        try:
            action_file = self._watcher.create_action_file(source)
            self._watcher.logger.info(f"Action file created: {action_file.name}")
            self._watcher.log_action(
                action_type="file_drop_detected",
                target=str(source),
                result="success",
                details={"action_file": action_file.name},
            )
        except Exception as err:
            self._watcher.logger.error(f"Error processing {source.name}: {err}")
            self._watcher.log_action(
                action_type="file_drop_detected",
                target=str(source),
                result="error",
                details={"error": str(err)},
            )


# ──────────────────────────────────────────────────────────────────────
# FilesystemWatcher
# ──────────────────────────────────────────────────────────────────────

class FilesystemWatcher(BaseWatcher):
    """
    Watches AI_Employee_Vault/Inbox/ for new files.

    On detection it:
      - Copies the file to Needs_Action/ (preserving metadata)
      - Creates a companion FILE_<name>.md action file with frontmatter
    """

    def __init__(self, vault_path: str):
        super().__init__(vault_path, check_interval=5)
        self.inbox = self.vault_path / "Inbox"
        self.inbox.mkdir(parents=True, exist_ok=True)
        self._seen: set[str] = set()

    # ------------------------------------------------------------------
    # BaseWatcher interface
    # ------------------------------------------------------------------

    def check_for_updates(self) -> list:
        """
        Not used in event-driven mode (watchdog handles detection).
        Kept to satisfy the abstract interface; also used for a one-shot
        scan on startup to catch files dropped while watcher was offline.
        """
        new_files = []
        for f in self.inbox.iterdir():
            if f.is_file() and not f.name.startswith(".") and f.name not in self._seen:
                new_files.append(f)
                self._seen.add(f.name)
        return new_files

    def create_action_file(self, item: Path) -> Path:
        """
        Given a file path (from Inbox), create a .md action file in Needs_Action/.

        The action file has YAML frontmatter that Claude Code reads to decide
        what to do with the dropped file.
        """
        now = datetime.now(timezone.utc)
        safe_name = item.name.replace(" ", "_")
        action_filename = f"FILE_{safe_name}.md"
        action_path = self.needs_action / action_filename

        # Avoid duplicate action files
        if action_path.exists():
            self.logger.warning(f"Action file already exists, skipping: {action_filename}")
            return action_path

        # Build file size string
        try:
            size_bytes = item.stat().st_size
            size_str = f"{size_bytes:,} bytes"
        except OSError:
            size_str = "unknown"

        content = f"""---
type: file_drop
source_file: {item.name}
source_path: {item}
size: {size_str}
received: {now.isoformat()}
status: pending
priority: normal
---

## File Received

A new file was dropped into the Inbox and requires processing.

| Field        | Value                    |
|--------------|--------------------------|
| File Name    | `{item.name}`            |
| Size         | {size_str}               |
| Received     | {now.strftime("%Y-%m-%d %H:%M UTC")} |
| Status       | pending                  |

## Suggested Actions

- [ ] Review the file contents
- [ ] Determine the appropriate action (summarize / file / forward / delete)
- [ ] Create a Plan file if multi-step processing is needed
- [ ] Move this file to `/Done` when complete

## Notes

_Add any context or instructions here before passing to Claude._
"""
        action_path.write_text(content, encoding="utf-8")

        # Mark as seen so the startup scan doesn't re-create it
        self._seen.add(item.name)
        return action_path

    # ------------------------------------------------------------------
    # Run (overrides base — uses watchdog observer instead of poll loop)
    # ------------------------------------------------------------------

    def run(self) -> None:
        """
        Start the watchdog observer on the Inbox folder.
        Performs a one-shot startup scan first to catch pre-existing files,
        then runs the real-time event-driven observer.
        """
        self.logger.info(f"Filesystem Watcher starting — monitoring: {self.inbox}")
        self.logger.info("Press Ctrl+C to stop.\n")

        # One-shot scan for files already in Inbox
        existing = self.check_for_updates()
        if existing:
            self.logger.info(f"Startup scan: {len(existing)} file(s) already in Inbox")
            for f in existing:
                try:
                    af = self.create_action_file(f)
                    self.logger.info(f"  → Created action file: {af.name}")
                except Exception as err:
                    self.logger.error(f"  ✗ Error for {f.name}: {err}")
        else:
            self.logger.info("Startup scan: Inbox is empty — watching for new files...")

        # Real-time observer
        handler = _InboxHandler(self)
        observer = Observer()
        observer.schedule(handler, str(self.inbox), recursive=False)
        observer.start()

        try:
            import time
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.logger.info("Stopping watcher...")
        finally:
            observer.stop()
            observer.join()
            self.logger.info("Filesystem Watcher stopped.")


# ──────────────────────────────────────────────────────────────────────
# CLI entry point
# ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="AI Employee — Filesystem Watcher (Bronze Tier)"
    )
    parser.add_argument(
        "--vault",
        default=os.getenv("VAULT_PATH", "AI_Employee_Vault"),
        help="Path to the Obsidian vault directory (default: AI_Employee_Vault or $VAULT_PATH)",
    )
    args = parser.parse_args()

    vault = Path(args.vault).resolve()
    if not vault.exists():
        print(f"ERROR: Vault path does not exist: {vault}")
        print("  Create the vault first, or check your --vault argument / VAULT_PATH env var.")
        raise SystemExit(1)

    watcher = FilesystemWatcher(str(vault))
    watcher.run()


if __name__ == "__main__":
    main()
