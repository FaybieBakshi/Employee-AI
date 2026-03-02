"""
signal_processor.py — Reads Signals/ folder and updates Dashboard.md system table.

Signals are JSON files written by cloud/health_monitor.py:
  Signals/health_cloud.json   — cloud agent health status
  Signals/health_local.json   — local agent health status (future)

This processor runs on the Local agent. It reads all signal files and updates
the "## System Status" table in Dashboard.md. Cloud never writes Dashboard.md
directly — it writes update fragments to Updates/ which this processor merges.

Usage:
  python sync/signal_processor.py          # run loop
  python sync/signal_processor.py --once   # process once and exit

Environment variables:
  VAULT_PATH             — path to vault (default: AI_Employee_Vault)
  SIGNAL_CHECK_INTERVAL  — seconds between checks (default: 15)
"""

import argparse
import json
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("sync.signal_processor")

VAULT_PATH = Path(os.getenv("VAULT_PATH", "AI_Employee_Vault")).resolve()
SIGNAL_CHECK_INTERVAL = int(os.getenv("SIGNAL_CHECK_INTERVAL", "15"))


def _read_signal(signal_file: Path) -> dict | None:
    """Read and parse a JSON signal file."""
    try:
        return json.loads(signal_file.read_text(encoding="utf-8"))
    except Exception as err:
        logger.warning(f"Failed to read signal {signal_file.name}: {err}")
        return None


def _format_status_row(agent: str, data: dict) -> str:
    """Format a markdown table row for the system status table."""
    status = data.get("status", "unknown")
    ts = data.get("timestamp", "")
    checks = data.get("checks", {})
    details = ", ".join(f"{k}:{v}" for k, v in checks.items()) if checks else "—"
    icon = "✅" if status == "healthy" else ("⚠️" if status == "degraded" else "❌")
    return f"| {agent} | {icon} {status} | {ts[:19] if ts else '—'} | {details} |"


def merge_updates_to_dashboard() -> int:
    """
    Process all files in Updates/ and append them to Dashboard.md.
    Returns the number of updates merged.
    """
    updates_dir = VAULT_PATH / "Updates"
    dashboard = VAULT_PATH / "Dashboard.md"

    if not updates_dir.exists():
        return 0

    update_files = sorted(updates_dir.glob("UPDATE_*.md"))
    if not update_files:
        return 0

    merged_content = ""
    processed = []
    for uf in update_files:
        try:
            content = uf.read_text(encoding="utf-8").strip()
            if content:
                merged_content += f"\n\n{content}"
            processed.append(uf)
        except Exception as err:
            logger.warning(f"Failed to read update file {uf.name}: {err}")

    if not merged_content:
        return 0

    # Append to Dashboard.md
    if dashboard.exists():
        existing = dashboard.read_text(encoding="utf-8")
    else:
        existing = "# Dashboard\n"

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    dashboard.write_text(
        existing + f"\n\n---\n<!-- Updates merged at {timestamp} -->\n{merged_content}\n",
        encoding="utf-8",
    )

    # Archive processed update files
    archive_dir = VAULT_PATH / "Updates" / "processed"
    archive_dir.mkdir(exist_ok=True)
    for uf in processed:
        uf.rename(archive_dir / uf.name)

    logger.info(f"Merged {len(processed)} update(s) into Dashboard.md")
    return len(processed)


def update_system_status_table() -> None:
    """
    Read all Signals/*.json files and update the ## System Status section
    in Dashboard.md. Creates the section if it doesn't exist.
    """
    signals_dir = VAULT_PATH / "Signals"
    dashboard = VAULT_PATH / "Dashboard.md"

    if not signals_dir.exists():
        return

    signal_files = list(signals_dir.glob("health_*.json"))
    if not signal_files:
        return

    rows = [
        "| Agent | Status | Last Check | Details |",
        "|-------|--------|------------|---------|",
    ]
    for sf in sorted(signal_files):
        data = _read_signal(sf)
        if data:
            agent = sf.stem.replace("health_", "")
            rows.append(_format_status_row(agent, data))

    table = "\n".join(rows)
    new_section = f"## System Status\n\n{table}\n"

    if not dashboard.exists():
        dashboard.write_text(f"# Dashboard\n\n{new_section}", encoding="utf-8")
        return

    content = dashboard.read_text(encoding="utf-8")

    # Replace existing ## System Status section or append
    pattern = r"## System Status\n[\s\S]*?(?=\n## |\Z)"
    if re.search(pattern, content):
        content = re.sub(pattern, new_section, content)
    else:
        content = content.rstrip() + f"\n\n{new_section}"

    dashboard.write_text(content, encoding="utf-8")
    logger.debug("Updated System Status table in Dashboard.md")


def process_signals_once() -> None:
    """Run one cycle: merge updates + refresh system status table."""
    try:
        count = merge_updates_to_dashboard()
        if count:
            logger.info(f"Merged {count} updates")
    except Exception as err:
        logger.error(f"Error merging updates: {err}")

    try:
        update_system_status_table()
    except Exception as err:
        logger.error(f"Error updating status table: {err}")


# ──────────────────────────────────────────────────────────────────────
# SignalProcessor — runnable class
# ──────────────────────────────────────────────────────────────────────

class SignalProcessor:
    """Long-running signal processing loop."""

    def __init__(self, interval: int = SIGNAL_CHECK_INTERVAL):
        self.interval = interval
        self._stop = threading.Event()
        self.logger = logging.getLogger("sync.SignalProcessor")

    def run(self) -> None:
        self.logger.info(f"SignalProcessor starting (interval={self.interval}s)")
        while not self._stop.is_set():
            process_signals_once()
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
    parser = argparse.ArgumentParser(description="Signal processor (Platinum Tier)")
    parser.add_argument("--once", action="store_true", help="Process once and exit")
    parser.add_argument("--interval", type=int, default=SIGNAL_CHECK_INTERVAL)
    args = parser.parse_args()

    if args.once:
        process_signals_once()
        return

    sp = SignalProcessor(interval=args.interval)
    sp.run()


if __name__ == "__main__":
    main()
