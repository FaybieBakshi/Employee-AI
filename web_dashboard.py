"""
web_dashboard.py — AI Employee Web Dashboard

Serves a real-time web UI at http://localhost:8080
Reads vault state live from markdown files — no database needed.

Usage:
    python web_dashboard.py
    python web_dashboard.py --port 8080 --vault AI_Employee_Vault
"""

import argparse
import json
import os
import re
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from dotenv import load_dotenv

load_dotenv()

VAULT_PATH = Path(os.getenv("VAULT_PATH", "AI_Employee_Vault")).resolve()


# ─────────────────────────────────────────────────────────
# Vault data readers
# ─────────────────────────────────────────────────────────

def count_files(folder: Path) -> int:
    if not folder.exists():
        return 0
    return sum(1 for f in folder.iterdir() if f.is_file() and f.suffix == ".md" and f.name != ".gitkeep")


def read_recent_activity(dashboard_path: Path) -> list[str]:
    if not dashboard_path.exists():
        return []
    text = dashboard_path.read_text(encoding="utf-8")
    section = re.search(r"## Recent Activity\n(.*?)(?=\n---|\Z)", text, re.DOTALL)
    if not section:
        return []
    lines = [l.strip() for l in section.group(1).strip().splitlines() if l.strip().startswith("-")]
    return lines[:8]


def read_pending_approvals(pending_dir: Path) -> list[dict]:
    items = []
    if not pending_dir.exists():
        return items
    for f in sorted(pending_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if f.suffix != ".md" or f.name == ".gitkeep":
            continue
        text = f.read_text(encoding="utf-8")
        from_match = re.search(r"^from:\s*(.+)", text, re.MULTILINE)
        subject_match = re.search(r"^subject:\s*(.+)", text, re.MULTILINE)
        action_match = re.search(r"^action:\s*(.+)", text, re.MULTILINE)
        items.append({
            "file": f.name,
            "from": from_match.group(1).strip() if from_match else "—",
            "subject": subject_match.group(1).strip() if subject_match else f.stem,
            "action": action_match.group(1).strip() if action_match else "review",
        })
    return items


def read_today_log() -> list[dict]:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    log_path = VAULT_PATH / "Logs" / f"{today}.json"
    if not log_path.exists():
        return []
    try:
        entries = json.loads(log_path.read_text(encoding="utf-8"))
        return list(reversed(entries[-20:]))
    except Exception:
        return []


def get_vault_stats() -> dict:
    return {
        "inbox": count_files(VAULT_PATH / "Inbox"),
        "needs_action": count_files(VAULT_PATH / "Needs_Action"),
        "in_progress": count_files(VAULT_PATH / "In_Progress"),
        "pending_approval": count_files(VAULT_PATH / "Pending_Approval"),
        "plans": count_files(VAULT_PATH / "Plans"),
        "done": count_files(VAULT_PATH / "Done"),
        "approved": count_files(VAULT_PATH / "Approved"),
        "rejected": count_files(VAULT_PATH / "Rejected"),
    }


def read_plans(limit: int = 10) -> list[dict]:
    plans_dir = VAULT_PATH / "Plans"
    if not plans_dir.exists():
        return []
    files = sorted(
        [f for f in plans_dir.iterdir() if f.suffix == ".md" and f.name != ".gitkeep"],
        key=lambda x: x.stat().st_mtime,
        reverse=True
    )
    items = []
    for f in files[:limit]:
        text = f.read_text(encoding="utf-8")
        status_match = re.search(r"^status:\s*(.+)", text, re.MULTILINE)
        category_match = re.search(r"^category:\s*(.+)", text, re.MULTILINE)
        source_match = re.search(r"^source:\s*(.+)", text, re.MULTILINE)
        items.append({
            "file": f.name,
            "source": source_match.group(1).strip() if source_match else f.stem,
            "status": status_match.group(1).strip() if status_match else "unknown",
            "category": category_match.group(1).strip() if category_match else "—",
        })
    return items


# ─────────────────────────────────────────────────────────
# HTML renderer
# ─────────────────────────────────────────────────────────

def status_badge(status: str) -> str:
    colors = {
        "completed": "#22c55e", "complete": "#22c55e",
        "in_progress": "#3b82f6", "active": "#3b82f6",
        "pending": "#f59e0b", "blocked": "#ef4444",
        "review": "#a855f7",
    }
    color = colors.get(status.lower(), "#6b7280")
    return f'<span style="background:{color};color:white;padding:2px 8px;border-radius:12px;font-size:11px;font-weight:600">{status}</span>'


def render_dashboard() -> str:
    stats = get_vault_stats()
    activity = read_recent_activity(VAULT_PATH / "Dashboard.md")
    pending = read_pending_approvals(VAULT_PATH / "Pending_Approval")
    logs = read_today_log()
    plans = read_plans()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Activity rows
    activity_rows = ""
    for line in activity:
        # Extract timestamp and message
        ts_match = re.search(r"\[([^\]]+)\]", line)
        msg = re.sub(r"- \[[^\]]+\]\s*", "", line).strip()
        ts = ts_match.group(1) if ts_match else ""
        activity_rows += f"""
        <tr>
          <td style="color:#94a3b8;font-size:12px;white-space:nowrap">{ts}</td>
          <td style="padding-left:12px">{msg}</td>
        </tr>"""

    # Pending approval rows
    pending_rows = ""
    if pending:
        for item in pending:
            pending_rows += f"""
        <tr>
          <td style="font-size:12px;color:#94a3b8">{item['action']}</td>
          <td style="padding-left:8px">{item['subject']}</td>
          <td style="padding-left:8px;color:#94a3b8;font-size:12px">{item['from']}</td>
        </tr>"""
    else:
        pending_rows = '<tr><td colspan="3" style="color:#6b7280;padding:12px 0">No pending approvals</td></tr>'

    # Audit log rows
    log_rows = ""
    for entry in logs[:12]:
        ts = entry.get("timestamp", "")[:19].replace("T", " ")
        action = entry.get("action_type", "")
        target = Path(entry.get("target", "")).name
        result = entry.get("result", "")
        result_color = "#22c55e" if result == "success" else "#ef4444"
        log_rows += f"""
        <tr>
          <td style="color:#94a3b8;font-size:11px;white-space:nowrap">{ts}</td>
          <td style="padding-left:8px;font-size:12px">{action}</td>
          <td style="padding-left:8px;color:#94a3b8;font-size:11px">{target}</td>
          <td style="padding-left:8px"><span style="color:{result_color};font-size:11px">{result}</span></td>
        </tr>"""
    if not log_rows:
        log_rows = '<tr><td colspan="4" style="color:#6b7280;padding:12px 0">No log entries today</td></tr>'

    # Plans rows
    plans_rows = ""
    for p in plans:
        plans_rows += f"""
        <tr>
          <td style="font-size:12px">{p['source']}</td>
          <td style="padding-left:8px">{status_badge(p['status'])}</td>
          <td style="padding-left:8px;color:#94a3b8;font-size:12px">{p['category']}</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="refresh" content="30">
  <title>AI Employee Dashboard</title>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f172a; color: #e2e8f0; min-height: 100vh; }}
    .header {{ background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%); border-bottom: 1px solid #1e3a5f; padding: 20px 32px; display: flex; justify-content: space-between; align-items: center; }}
    .header h1 {{ font-size: 22px; font-weight: 700; color: #f1f5f9; }}
    .header h1 span {{ color: #38bdf8; }}
    .header .meta {{ font-size: 12px; color: #64748b; text-align: right; }}
    .badge-live {{ background: #22c55e; color: white; font-size: 10px; font-weight: 700; padding: 2px 7px; border-radius: 10px; margin-left: 8px; animation: pulse 2s infinite; }}
    @keyframes pulse {{ 0%,100%{{opacity:1}} 50%{{opacity:0.6}} }}
    .container {{ max-width: 1400px; margin: 0 auto; padding: 24px 32px; }}
    .stats-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 24px; }}
    @media(max-width:900px) {{ .stats-grid {{ grid-template-columns: repeat(2,1fr); }} }}
    .stat-card {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 20px; }}
    .stat-card .label {{ font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: #64748b; margin-bottom: 8px; }}
    .stat-card .value {{ font-size: 36px; font-weight: 700; line-height: 1; }}
    .stat-card .sub {{ font-size: 12px; color: #64748b; margin-top: 4px; }}
    .v-inbox {{ color: #38bdf8; }}
    .v-needs {{ color: #f59e0b; }}
    .v-pending {{ color: #a855f7; }}
    .v-done {{ color: #22c55e; }}
    .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px; }}
    @media(max-width:900px) {{ .grid-2 {{ grid-template-columns: 1fr; }} }}
    .card {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 20px; }}
    .card h3 {{ font-size: 13px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: #94a3b8; margin-bottom: 16px; display: flex; align-items: center; gap: 8px; }}
    .card h3 .dot {{ width: 8px; height: 8px; border-radius: 50%; background: #38bdf8; }}
    table {{ width: 100%; border-collapse: collapse; }}
    tr {{ border-bottom: 1px solid #1e3a5f; }}
    tr:last-child {{ border-bottom: none; }}
    td {{ padding: 8px 4px; vertical-align: top; }}
    .footer {{ text-align: center; color: #334155; font-size: 12px; padding: 24px; }}
    .refresh-note {{ font-size: 11px; color: #475569; margin-top: 4px; }}
  </style>
</head>
<body>
  <div class="header">
    <div>
      <h1>AI Employee <span>Vault</span><span class="badge-live">LIVE</span></h1>
      <div style="font-size:12px;color:#64748b;margin-top:4px">Personal AI Employee — Gold Tier v0.3.0</div>
    </div>
    <div class="meta">
      <div>Last refreshed: {now}</div>
      <div class="refresh-note">Auto-refreshes every 30 seconds</div>
    </div>
  </div>

  <div class="container">

    <!-- Stats Row -->
    <div class="stats-grid">
      <div class="stat-card">
        <div class="label">Inbox</div>
        <div class="value v-inbox">{stats['inbox']}</div>
        <div class="sub">unprocessed files</div>
      </div>
      <div class="stat-card">
        <div class="label">Needs Action</div>
        <div class="value v-needs">{stats['needs_action']}</div>
        <div class="sub">awaiting reasoning loop</div>
      </div>
      <div class="stat-card">
        <div class="label">Pending Approval</div>
        <div class="value v-pending">{stats['pending_approval']}</div>
        <div class="sub">awaiting your review</div>
      </div>
      <div class="stat-card">
        <div class="label">Done Today</div>
        <div class="value v-done">{stats['done']}</div>
        <div class="sub">{stats['plans']} plans created</div>
      </div>
    </div>

    <!-- Row 2: Activity + Pending Approval -->
    <div class="grid-2">
      <div class="card">
        <h3><span class="dot"></span>Recent Activity</h3>
        <table>
          {activity_rows if activity_rows else '<tr><td style="color:#6b7280">No activity yet</td></tr>'}
        </table>
      </div>
      <div class="card">
        <h3><span class="dot" style="background:#a855f7"></span>Pending Approval</h3>
        <table>
          {pending_rows}
        </table>
      </div>
    </div>

    <!-- Row 3: Plans + Audit Log -->
    <div class="grid-2">
      <div class="card">
        <h3><span class="dot" style="background:#22c55e"></span>Recent Plans</h3>
        <table>
          {plans_rows if plans_rows else '<tr><td style="color:#6b7280">No plans yet</td></tr>'}
        </table>
      </div>
      <div class="card">
        <h3><span class="dot" style="background:#f59e0b"></span>Today's Audit Log</h3>
        <table>
          {log_rows}
        </table>
      </div>
    </div>

    <!-- Row 4: Secondary stats -->
    <div class="stats-grid" style="grid-template-columns: repeat(4,1fr); margin-top:0">
      <div class="stat-card" style="padding:14px 20px">
        <div class="label">In Progress</div>
        <div class="value" style="font-size:24px;color:#38bdf8">{stats['in_progress']}</div>
      </div>
      <div class="stat-card" style="padding:14px 20px">
        <div class="label">Approved</div>
        <div class="value" style="font-size:24px;color:#22c55e">{stats['approved']}</div>
      </div>
      <div class="stat-card" style="padding:14px 20px">
        <div class="label">Rejected</div>
        <div class="value" style="font-size:24px;color:#ef4444">{stats['rejected']}</div>
      </div>
      <div class="stat-card" style="padding:14px 20px">
        <div class="label">Plans Total</div>
        <div class="value" style="font-size:24px;color:#94a3b8">{stats['plans']}</div>
      </div>
    </div>

  </div>
  <div class="footer">
    AI Employee Dashboard — reads live from vault at <code style="color:#38bdf8">{VAULT_PATH}</code>
  </div>
</body>
</html>"""


# ─────────────────────────────────────────────────────────
# HTTP server
# ─────────────────────────────────────────────────────────

class DashboardHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/api/stats":
            data = json.dumps(get_vault_stats())
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data.encode())
            return

        if parsed.path in ("/", "/dashboard"):
            html = render_dashboard()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
            return

        self.send_response(404)
        self.end_headers()
        self.wfile.write(b"Not found")

    def log_message(self, fmt, *args):
        # Suppress default access log spam
        pass


def main():
    parser = argparse.ArgumentParser(description="AI Employee Web Dashboard")
    parser.add_argument("--port", type=int, default=8080, help="Port to serve on (default: 8080)")
    parser.add_argument("--host", default="localhost", help="Host to bind to (default: localhost)")
    parser.add_argument("--vault", default=os.getenv("VAULT_PATH", "AI_Employee_Vault"))
    args = parser.parse_args()

    global VAULT_PATH
    VAULT_PATH = Path(args.vault).resolve()

    if not VAULT_PATH.exists():
        print(f"ERROR: Vault not found at {VAULT_PATH}")
        raise SystemExit(1)

    server = HTTPServer((args.host, args.port), DashboardHandler)
    url = f"http://{args.host}:{args.port}"
    print(f"AI Employee Dashboard running at {url}")
    print(f"Vault: {VAULT_PATH}")
    print(f"Auto-refreshes every 30 seconds. Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDashboard stopped.")


if __name__ == "__main__":
    main()
