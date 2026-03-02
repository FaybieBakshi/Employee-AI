"""
health_monitor.py — Cloud agent heartbeat and service health checks (Platinum Tier).

Writes Signals/health_cloud.json every HEALTH_CHECK_INTERVAL seconds.

Checks performed:
  - Odoo XMLRPC reachability
  - SMTP connectivity
  - Disk space (vault filesystem)
  - Git repo status (can push/pull)

Signal file format:
  {
    "agent": "cloud",
    "status": "healthy" | "degraded" | "unhealthy",
    "timestamp": "2026-03-02T10:00:00Z",
    "checks": {
      "odoo": "ok" | "error: ...",
      "smtp": "ok" | "error: ...",
      "disk_free_gb": 12.3,
      "git": "ok" | "error: ..."
    }
  }

Usage:
  python cloud/health_monitor.py          # run loop
  python cloud/health_monitor.py --once   # check once and exit

Environment variables:
  VAULT_PATH              — path to vault (default: AI_Employee_Vault)
  HEALTH_CHECK_INTERVAL   — seconds between checks (default: 30)
  ODOO_URL                — Odoo instance URL
  SMTP_HOST / SMTP_PORT   — SMTP server for connectivity check
"""

import argparse
import json
import logging
import os
import smtplib
import socket
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("cloud.health_monitor")

VAULT_PATH = Path(os.getenv("VAULT_PATH", "AI_Employee_Vault")).resolve()
HEALTH_CHECK_INTERVAL = int(os.getenv("HEALTH_CHECK_INTERVAL", "30"))
ODOO_URL = os.getenv("ODOO_URL", "")
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SIGNAL_PATH = VAULT_PATH / "Signals" / "health_cloud.json"


def _check_odoo() -> str:
    """Check Odoo XMLRPC reachability."""
    if not ODOO_URL:
        return "skipped (ODOO_URL not set)"
    try:
        import xmlrpc.client
        proxy = xmlrpc.client.ServerProxy(
            f"{ODOO_URL}/xmlrpc/2/common",
            allow_none=True,
        )
        proxy.version()
        return "ok"
    except Exception as err:
        return f"error: {err}"


def _check_smtp() -> str:
    """Check SMTP TCP reachability (no auth)."""
    try:
        with socket.create_connection((SMTP_HOST, SMTP_PORT), timeout=5):
            return "ok"
    except Exception as err:
        return f"error: {err}"


def _check_disk() -> float:
    """Return free disk space in GB on the vault filesystem."""
    try:
        import shutil
        usage = shutil.disk_usage(str(VAULT_PATH))
        return round(usage.free / (1024 ** 3), 2)
    except Exception:
        return -1.0


def _check_git() -> str:
    """Check if git repo is accessible."""
    try:
        import subprocess
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            capture_output=True,
            text=True,
            cwd=str(VAULT_PATH.parent),
            timeout=10,
        )
        return "ok" if result.returncode == 0 else f"error: {result.stderr.strip()}"
    except Exception as err:
        return f"error: {err}"


def run_health_check() -> dict:
    """Run all health checks and return the signal data dict."""
    checks = {
        "odoo": _check_odoo(),
        "smtp": _check_smtp(),
        "disk_free_gb": _check_disk(),
        "git": _check_git(),
    }

    # Determine overall status
    errors = [v for k, v in checks.items() if isinstance(v, str) and v.startswith("error")]
    if len(errors) == 0:
        status = "healthy"
    elif len(errors) < len([v for v in checks.values() if isinstance(v, str)]):
        status = "degraded"
    else:
        status = "unhealthy"

    return {
        "agent": "cloud",
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
    }


def write_signal(data: dict) -> None:
    """Write health signal to Signals/health_cloud.json."""
    SIGNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
    SIGNAL_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    logger.debug(f"Health signal written: status={data['status']}")


# ──────────────────────────────────────────────────────────────────────
# HealthMonitor — runnable class
# ──────────────────────────────────────────────────────────────────────

class HealthMonitor:
    """Long-running health check loop."""

    def __init__(self, interval: int = HEALTH_CHECK_INTERVAL):
        self.interval = interval
        self._stop = threading.Event()
        self.logger = logging.getLogger("cloud.HealthMonitor")

    def run(self) -> None:
        self.logger.info(f"HealthMonitor starting (interval={self.interval}s)")
        while not self._stop.is_set():
            try:
                data = run_health_check()
                write_signal(data)
                if data["status"] != "healthy":
                    self.logger.warning(f"Health: {data['status']} — {data['checks']}")
                else:
                    self.logger.debug(f"Health: {data['status']}")
            except Exception as err:
                self.logger.error(f"Health check error: {err}")
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
    parser = argparse.ArgumentParser(description="Cloud health monitor (Platinum Tier)")
    parser.add_argument("--once", action="store_true", help="Check once and exit")
    parser.add_argument("--interval", type=int, default=HEALTH_CHECK_INTERVAL)
    args = parser.parse_args()

    if args.once:
        data = run_health_check()
        write_signal(data)
        print(json.dumps(data, indent=2))
        return

    hm = HealthMonitor(interval=args.interval)
    hm.run()


if __name__ == "__main__":
    main()
