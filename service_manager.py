"""
service_manager.py — AI Employee Windows Service Manager

Starts all components as background processes (no console window).
Uses pythonw.exe so nothing appears in the taskbar.

Commands:
    python service_manager.py start      — start all services
    python service_manager.py stop       — stop all services
    python service_manager.py restart    — restart all services
    python service_manager.py status     — show what is running
    python service_manager.py install    — register with Windows Task Scheduler (auto-start on login)
    python service_manager.py uninstall  — remove from Task Scheduler

Services managed:
    orchestrator   — filesystem + gmail + approval watchers
    dashboard      — web UI at http://localhost:8080
    scheduler      — daily briefings, weekly audit
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).resolve().parent
PID_FILE = BASE_DIR / ".services.json"
LOG_DIR = BASE_DIR / "logs"

# ─── Python executable ───────────────────────────────────────────────
# pythonw.exe = runs without a console window on Windows
PYTHON = sys.executable
PYTHONW = PYTHON.replace("python.exe", "pythonw.exe")
if not Path(PYTHONW).exists():
    PYTHONW = PYTHON  # fallback to python.exe on non-Windows

SERVICES = {
    "orchestrator": {
        "script": str(BASE_DIR / "orchestrator.py"),
        "args": ["--watchers", "fs,gmail,approval"],
        "description": "Filesystem + Gmail + Approval watchers",
    },
    "dashboard": {
        "script": str(BASE_DIR / "web_dashboard.py"),
        "args": ["--port", "8080"],
        "description": "Web dashboard at http://localhost:8080",
    },
    "scheduler": {
        "script": str(BASE_DIR / "scheduler.py"),
        "args": [],
        "description": "Daily briefings + weekly audit scheduler",
    },
}


# ─── PID file helpers ─────────────────────────────────────────────────

def _load_pids() -> dict:
    if PID_FILE.exists():
        try:
            return json.loads(PID_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_pids(pids: dict) -> None:
    PID_FILE.write_text(json.dumps(pids, indent=2), encoding="utf-8")


def _is_running(pid: int) -> bool:
    """Check if a PID is alive (Windows-compatible)."""
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, text=True
        )
        return str(pid) in result.stdout
    except Exception:
        return False


# ─── Log file ─────────────────────────────────────────────────────────

def _log_path(name: str) -> Path:
    LOG_DIR.mkdir(exist_ok=True)
    return LOG_DIR / f"{name}.log"


# ─── Commands ─────────────────────────────────────────────────────────

def cmd_start(services: list[str] = None):
    """Start all (or named) services in the background."""
    pids = _load_pids()
    targets = services or list(SERVICES.keys())

    for name in targets:
        if name not in SERVICES:
            print(f"  Unknown service: {name}")
            continue

        # Skip if already running
        existing_pid = pids.get(name)
        if existing_pid and _is_running(existing_pid):
            print(f"  {name:<14} already running (PID {existing_pid})")
            continue

        svc = SERVICES[name]
        log = _log_path(name)
        cmd = [PYTHONW, svc["script"]] + svc["args"]

        try:
            with open(log, "a") as logf:
                logf.write(f"\n--- Started {datetime.now().isoformat()} ---\n")
                proc = subprocess.Popen(
                    cmd,
                    cwd=str(BASE_DIR),
                    stdout=logf,
                    stderr=logf,
                    # No new console window
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                )
            pids[name] = proc.pid
            print(f"  {name:<14} started  (PID {proc.pid})  log: logs/{name}.log")
        except Exception as e:
            print(f"  {name:<14} FAILED: {e}")

    _save_pids(pids)
    print()
    print("Dashboard: http://localhost:8080")


def cmd_stop(services: list[str] = None):
    """Stop all (or named) services."""
    pids = _load_pids()
    targets = services or list(SERVICES.keys())

    for name in targets:
        pid = pids.get(name)
        if not pid:
            print(f"  {name:<14} not tracked (no PID)")
            continue

        if not _is_running(pid):
            print(f"  {name:<14} already stopped")
            pids.pop(name, None)
            continue

        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/F"],
                           capture_output=True)
            print(f"  {name:<14} stopped  (PID {pid})")
            pids.pop(name, None)
        except Exception as e:
            print(f"  {name:<14} error stopping: {e}")

    _save_pids(pids)


def cmd_status():
    """Show running state of all services."""
    pids = _load_pids()
    print(f"\n{'Service':<16} {'Status':<10} {'PID':<8} Description")
    print("-" * 70)
    for name, svc in SERVICES.items():
        pid = pids.get(name)
        if pid and _is_running(pid):
            status = "RUNNING"
            color_start, color_end = "\033[92m", "\033[0m"  # green
        else:
            status = "STOPPED"
            pid = "—"
            color_start, color_end = "\033[91m", "\033[0m"  # red

        try:
            print(f"{name:<16} {color_start}{status:<10}{color_end} {str(pid):<8} {svc['description']}")
        except Exception:
            print(f"{name:<16} {status:<10} {str(pid):<8} {svc['description']}")

    print()
    log_exists = any(_log_path(n).exists() for n in SERVICES)
    if log_exists:
        print("Logs: logs/orchestrator.log | logs/dashboard.log | logs/scheduler.log")
    print("Dashboard: http://localhost:8080")
    print()


def cmd_restart(services: list[str] = None):
    """Restart all (or named) services."""
    targets = services or list(SERVICES.keys())
    cmd_stop(targets)
    time.sleep(1)
    cmd_start(targets)


def cmd_install():
    """Register all services with Windows Task Scheduler to auto-start on login."""
    if sys.platform != "win32":
        print("Task Scheduler install is Windows-only.")
        return

    script = str(BASE_DIR / "service_manager.py")
    task_cmd = f'"{PYTHON}" "{script}" start'

    print("Registering with Windows Task Scheduler...")
    print("(Services will auto-start next time you log in)\n")

    result = subprocess.run([
        "schtasks", "/Create",
        "/TN", "AIEmployee_AutoStart",
        "/TR", task_cmd,
        "/SC", "ONLOGON",
        "/RL", "HIGHEST",
        "/F",   # overwrite if exists
    ], capture_output=True, text=True)

    if result.returncode == 0:
        print("Task Scheduler: AIEmployee_AutoStart registered.")
        print("Services will start automatically each time you log in.")
        print()
        print("To remove auto-start later, run:")
        print("  python service_manager.py uninstall")
    else:
        print(f"Task Scheduler registration failed:\n{result.stderr}")
        print()
        print("Try running as Administrator:")
        print("  Right-click service_manager.py → Run as administrator")


def cmd_uninstall():
    """Remove from Windows Task Scheduler."""
    if sys.platform != "win32":
        print("Task Scheduler uninstall is Windows-only.")
        return

    result = subprocess.run([
        "schtasks", "/Delete",
        "/TN", "AIEmployee_AutoStart",
        "/F",
    ], capture_output=True, text=True)

    if result.returncode == 0:
        print("Removed AIEmployee_AutoStart from Task Scheduler.")
    else:
        print(f"Could not remove task: {result.stderr.strip()}")


# ─── CLI ──────────────────────────────────────────────────────────────

COMMANDS = {
    "start": cmd_start,
    "stop": cmd_stop,
    "restart": cmd_restart,
    "status": cmd_status,
    "install": cmd_install,
    "uninstall": cmd_uninstall,
}

HELP = """
AI Employee — Service Manager

Usage:
  python service_manager.py <command> [service ...]

Commands:
  start      [svc]   Start all services (or a specific one)
  stop       [svc]   Stop all services (or a specific one)
  restart    [svc]   Restart all services (or a specific one)
  status             Show what is running
  install            Register auto-start with Windows Task Scheduler
  uninstall          Remove from Windows Task Scheduler

Services: orchestrator | dashboard | scheduler

Examples:
  python service_manager.py start
  python service_manager.py stop dashboard
  python service_manager.py restart orchestrator
  python service_manager.py status
  python service_manager.py install
"""


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help", "help"):
        print(HELP)
        return

    cmd = args[0].lower()
    svc_args = args[1:] if len(args) > 1 else None

    if cmd not in COMMANDS:
        print(f"Unknown command: {cmd}")
        print("Run with --help to see available commands.")
        sys.exit(1)

    fn = COMMANDS[cmd]
    print(f"\nAI Employee — {cmd.upper()}")
    print("=" * 50)

    if cmd in ("start", "stop", "restart") and svc_args:
        fn(svc_args)
    else:
        fn()


if __name__ == "__main__":
    main()
