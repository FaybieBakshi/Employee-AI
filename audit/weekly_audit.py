"""
weekly_audit.py — Weekly Business & Accounting Audit with CEO Briefing (Gold Tier).

Runs every Monday at 08:00 (via scheduler.py).

Collects data from:
  - Odoo: revenue, invoices, expenses
  - Vault /Done: completed tasks this week
  - Vault /Logs: action counts, errors
  - Social /Social: engagement summaries
  - Vault /Pending_Approval: outstanding approvals

Generates:
  AI_Employee_Vault/Briefings/YYYY-MM-DD_Weekly_CEO_Briefing.md

Usage:
  python -m audit.weekly_audit
  python -m audit.weekly_audit --vault AI_Employee_Vault
"""

import json
import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


# ──────────────────────────────────────────────────────────────────────
# Data collectors
# ──────────────────────────────────────────────────────────────────────

def _collect_odoo_data() -> dict:
    """Try to collect Odoo accounting data. Gracefully skips if unavailable."""
    try:
        from odoo.client import OdooClient
        client = OdooClient()
        if not client.ping():
            return {"available": False, "reason": "Odoo not reachable"}
        revenue = client.get_revenue_summary()
        expenses = client.get_expense_summary()
        return {
            "available": True,
            "revenue": revenue,
            "expenses": expenses,
            "net": round(revenue["total_paid"] - expenses["total_expenses"], 2),
        }
    except Exception as err:
        return {"available": False, "reason": str(err)}


def _collect_done_tasks(vault_path: Path, days: int = 7) -> list[str]:
    """Get names of tasks completed in the last N days."""
    done_dir = vault_path / "Done"
    if not done_dir.exists():
        return []
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    recent = []
    for f in done_dir.iterdir():
        if f.suffix != ".md" or f.name.startswith("."):
            continue
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
            if mtime > cutoff:
                name = f.stem.replace("_", " ").replace("Plan ", "").replace("FILE ", "")
                recent.append(name)
        except OSError:
            pass
    return recent


def _collect_log_summary(vault_path: Path, days: int = 7) -> dict:
    """Aggregate log data from the last N days."""
    from audit.audit_logger import AuditLogger
    logger = AuditLogger(str(vault_path))
    entries = logger.get_weekly_entries()
    total = len(entries)
    errors = sum(1 for e in entries if e.get("result") == "error")
    by_domain: dict[str, int] = {}
    for e in entries:
        d = e.get("domain", "system")
        by_domain[d] = by_domain.get(d, 0) + 1
    return {"total_actions": total, "errors": errors, "by_domain": by_domain}


def _collect_social_summaries(vault_path: Path) -> list[str]:
    """Read most recent social summary files from /Social."""
    social_dir = vault_path / "Social"
    if not social_dir.exists():
        return []
    summaries = []
    for f in sorted(social_dir.glob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True)[:4]:
        text = f.read_text(encoding="utf-8")
        # Extract table rows
        rows = re.findall(r"\| ([^|]+) \| ([^|]+) \|", text)
        if rows:
            platform = f.stem.split("_")[0].title()
            metrics = " | ".join(f"{r[0].strip()}: {r[1].strip()}" for r in rows if "Metric" not in r[0])
            summaries.append(f"**{platform}:** {metrics}")
    return summaries


def _collect_subscription_flags(vault_path: Path) -> list[str]:
    """Check accounting log for recurring charges that may need review."""
    SUBSCRIPTION_PATTERNS = {
        "netflix": "Netflix", "spotify": "Spotify", "adobe": "Adobe",
        "notion": "Notion", "slack": "Slack", "zoom": "Zoom",
        "github": "GitHub", "figma": "Figma", "dropbox": "Dropbox",
    }
    flags = []
    accounting_dir = vault_path / "Accounting"
    if not accounting_dir.exists():
        return flags
    for f in accounting_dir.glob("*.md"):
        text = f.read_text(encoding="utf-8").lower()
        for pattern, name in SUBSCRIPTION_PATTERNS.items():
            if pattern in text:
                flags.append(f"- **{name}** detected in {f.name} — verify still in use")
    return flags


# ──────────────────────────────────────────────────────────────────────
# Briefing generator
# ──────────────────────────────────────────────────────────────────────

def generate_briefing(vault_path: str = None) -> Path:
    """
    Generate the weekly CEO briefing and save to /Briefings/.
    Returns path to the briefing file.
    """
    vault = Path(vault_path or os.getenv("VAULT_PATH", "AI_Employee_Vault")).resolve()
    briefings_dir = vault / "Briefings"
    briefings_dir.mkdir(exist_ok=True)

    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")
    week_start = (now - timedelta(days=7)).strftime("%Y-%m-%d")

    # Collect all data
    odoo = _collect_odoo_data()
    done_tasks = _collect_done_tasks(vault)
    log_summary = _collect_log_summary(vault)
    social_summaries = _collect_social_summaries(vault)
    subscriptions = _collect_subscription_flags(vault)
    pending_count = len(list((vault / "Pending_Approval").glob("*.md")))
    needs_action_count = len(list((vault / "Needs_Action").glob("*.md")))

    # Build accounting section
    if odoo["available"]:
        r = odoo["revenue"]
        e = odoo["expenses"]
        accounting_section = f"""## Accounting (Odoo)

| Metric | Amount |
|--------|--------|
| Total Invoiced | ${r['total_invoiced']:,.2f} |
| Total Paid | ${r['total_paid']:,.2f} |
| Outstanding | ${r['outstanding']:,.2f} |
| Total Expenses | ${e['total_expenses']:,.2f} |
| Net (Paid - Expenses) | ${odoo['net']:,.2f} |

*{r['invoice_count']} invoices total, {r['paid_count']} paid*"""
    else:
        accounting_section = f"""## Accounting (Odoo)

> Odoo not available: {odoo.get('reason', 'unknown')}
>
> Configure ODOO_URL, ODOO_DB, ODOO_USER, ODOO_PASSWORD in .env to enable."""

    # Build tasks section
    done_md = "\n".join(f"- [x] {t}" for t in done_tasks) if done_tasks else "- No tasks completed this week"

    # Build social section
    social_md = "\n".join(social_summaries) if social_summaries else "*No social data available*"

    # Build subscriptions section
    sub_md = "\n".join(subscriptions) if subscriptions else "- No subscription flags this week"

    # Compose briefing
    briefing = f"""---
generated: {now.isoformat()}
period: {week_start} to {date_str}
type: weekly_ceo_briefing
tier: gold
---

# Weekly CEO Briefing

*Generated by AI Employee — {date_str}*

---

## Executive Summary

| Metric | Value |
|--------|-------|
| Tasks Completed | {len(done_tasks)} |
| AI Actions Taken | {log_summary['total_actions']} |
| Errors | {log_summary['errors']} |
| Pending Approvals | {pending_count} |
| Needs Action Queue | {needs_action_count} |

---

{accounting_section}

---

## Completed Tasks This Week ({len(done_tasks)})

{done_md}

---

## Social Media Engagement

{social_md}

---

## AI Activity by Domain

| Domain | Actions |
|--------|---------|
{chr(10).join(f"| {domain} | {count} |" for domain, count in log_summary['by_domain'].items()) or "| — | 0 |"}

---

## Subscription Audit

{sub_md}

---

## Action Required

- Review **{pending_count}** item(s) in `/Pending_Approval`
- Process **{needs_action_count}** item(s) in `/Needs_Action`
{"- **" + str(log_summary['errors']) + " errors** detected — check /Logs/ for details" if log_summary['errors'] > 0 else ""}

---

*Generated by AI Employee v0.3.0 — Gold Tier*
"""

    filepath = briefings_dir / f"{date_str}_Weekly_CEO_Briefing.md"
    filepath.write_text(briefing, encoding="utf-8")
    return filepath


# ──────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="AI Employee — Weekly Audit (Gold Tier)")
    parser.add_argument("--vault", default=os.getenv("VAULT_PATH", "AI_Employee_Vault"))
    args = parser.parse_args()

    print("Generating Weekly CEO Briefing...")
    filepath = generate_briefing(args.vault)
    print(f"Briefing saved: {filepath}")
    print()
    print(filepath.read_text(encoding="utf-8")[:1000])


if __name__ == "__main__":
    main()
