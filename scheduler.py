"""
scheduler.py — Task scheduler for the AI Employee (Gold Tier).

Uses the `schedule` library to run timed tasks:
  - Daily 08:00  — Update Dashboard + process Needs_Action
  - Monday 08:00 — Generate full weekly CEO Briefing (Odoo + tasks + social + logs)
  - Sunday 20:00 — Generate LinkedIn post for the coming week
  - Every 30 min — Check Needs_Action item count and log

Runs as a daemon thread inside orchestrator.py, or standalone:
  python scheduler.py

Environment variables (.env):
  VAULT_PATH            — path to vault
  DAILY_BRIEFING_TIME   — HH:MM for daily dashboard update (default: 08:00)
  CEO_BRIEFING_DAY      — day for CEO briefing (default: monday)
  WEEKLY_AUDIT_TIME     — HH:MM for weekly audit (default: 08:00)
  LINKEDIN_POST_DAY     — day for LinkedIn post generation (default: sunday)
  LINKEDIN_POST_TIME    — HH:MM for LinkedIn post (default: 20:00)
"""

import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import schedule
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("scheduler")

VAULT_PATH = Path(os.getenv("VAULT_PATH", "AI_Employee_Vault")).resolve()
DAILY_TIME = os.getenv("DAILY_BRIEFING_TIME", "08:00")
CEO_DAY = os.getenv("CEO_BRIEFING_DAY", "monday")
WEEKLY_AUDIT_TIME = os.getenv("WEEKLY_AUDIT_TIME", "08:00")
LINKEDIN_DAY = os.getenv("LINKEDIN_POST_DAY", "sunday")
LINKEDIN_TIME = os.getenv("LINKEDIN_POST_TIME", "20:00")


# ──────────────────────────────────────────────────────────────────────
# Scheduled tasks
# ──────────────────────────────────────────────────────────────────────

def task_daily_dashboard_update() -> None:
    """Update Dashboard.md with current folder counts."""
    logger.info("[SCHEDULED] Running daily dashboard update")
    try:
        dashboard = VAULT_PATH / "Dashboard.md"
        if not dashboard.exists():
            logger.warning("Dashboard.md not found")
            return

        def count_md(folder: str) -> int:
            d = VAULT_PATH / folder
            if not d.exists():
                return 0
            return len([f for f in d.iterdir() if f.suffix == ".md" and not f.name.startswith(".")])

        inbox_count = len([f for f in (VAULT_PATH / "Inbox").iterdir()
                          if not f.name.startswith(".")]) if (VAULT_PATH / "Inbox").exists() else 0
        needs_action = count_md("Needs_Action")
        plans = count_md("Plans")
        done = count_md("Done")

        text = dashboard.read_text(encoding="utf-8")
        now = datetime.now(timezone.utc)

        # Update last_updated timestamp
        import re
        text = re.sub(r"last_updated:.*", f"last_updated: {now.isoformat()}", text)

        # Update counts table
        text = re.sub(r"\| Inbox \(unprocessed\)\|.*", f"| Inbox (unprocessed)| {inbox_count}     |", text)
        text = re.sub(r"\| Needs Action\s+\|.*", f"| Needs Action      | {needs_action}     |", text)
        text = re.sub(r"\| Plans Active\s+\|.*", f"| Plans Active      | {plans}     |", text)
        text = re.sub(r"\| Done \(today\)\s+\|.*", f"| Done (today)      | {done}     |", text)

        # Prepend recent activity
        activity_line = f"- [{now.strftime('%Y-%m-%d %H:%M UTC')}] Scheduled daily update — Needs_Action: {needs_action}, Plans: {plans}, Done: {done}"
        text = re.sub(r"(## Recent Activity\n)", f"\\1{activity_line}\n", text, count=1)

        dashboard.write_text(text, encoding="utf-8")
        logger.info(f"Dashboard updated — Needs_Action:{needs_action} Plans:{plans} Done:{done}")

    except Exception as err:
        logger.error(f"Daily dashboard update failed: {err}")


def task_ceo_briefing() -> None:
    """Generate a full weekly CEO Briefing using the Gold Tier audit module."""
    logger.info("[SCHEDULED] Generating Weekly CEO Briefing (Gold Tier)")
    try:
        from audit.weekly_audit import generate_briefing
        filepath = generate_briefing(str(VAULT_PATH))
        logger.info(f"CEO Briefing written: {filepath.name}")
    except ImportError:
        logger.warning("audit.weekly_audit not available — falling back to basic briefing")
        _task_ceo_briefing_basic()
    except Exception as err:
        logger.error(f"CEO Briefing generation failed: {err}")


def _task_ceo_briefing_basic() -> None:
    """Fallback: basic CEO briefing without Odoo/social data."""
    try:
        done_dir = VAULT_PATH / "Done"
        briefings_dir = VAULT_PATH / "Briefings"
        briefings_dir.mkdir(exist_ok=True)

        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y-%m-%d")

        done_files = sorted(
            [f for f in done_dir.iterdir() if f.suffix == ".md" and not f.name.startswith(".")],
            key=lambda f: f.stat().st_mtime, reverse=True
        )[:20] if done_dir.exists() else []

        done_list = "\n".join(f"- [x] {f.stem.replace('_', ' ')}" for f in done_files) or "- No tasks completed"

        briefing = f"""---
generated: {now.isoformat()}
period: Last 7 days
type: ceo_briefing
tier: basic
---

# Monday Morning CEO Briefing

*Generated by AI Employee — {date_str}*

## Completed Tasks ({len(done_files)} total)

{done_list}

## Pipeline

| Metric | Count |
|--------|-------|
| Needs Action | {len(list((VAULT_PATH / 'Needs_Action').glob('*.md')))} |
| Active Plans | {len(list((VAULT_PATH / 'Plans').glob('*.md')))} |
| Pending Approval | {len(list((VAULT_PATH / 'Pending_Approval').glob('*.md')))} |

---
*Generated by AI Employee v0.3.0 — Gold Tier*
"""
        filepath = briefings_dir / f"{date_str}_Monday_Briefing.md"
        filepath.write_text(briefing, encoding="utf-8")
        logger.info(f"Basic CEO Briefing written: {filepath.name}")

    except Exception as err:
        logger.error(f"Basic CEO Briefing failed: {err}")


def task_generate_linkedin_post() -> None:
    """Generate a LinkedIn post draft and save to Pending_Approval."""
    logger.info("[SCHEDULED] Generating LinkedIn post")
    try:
        import random
        from linkedin.post_generator import generate_post

        templates = ["insight", "milestone", "tips", "story"]
        template = random.choice(templates)

        filepath = generate_post(str(VAULT_PATH), template=template)
        logger.info(f"LinkedIn post draft created: {filepath.name}")
        logger.info(f"Review and move to /Approved to post: {filepath}")

    except ImportError:
        logger.warning("linkedin.post_generator not available")
    except Exception as err:
        logger.error(f"LinkedIn post generation failed: {err}")


def task_check_needs_action() -> None:
    """Log the current count of pending Needs_Action items."""
    needs_action = VAULT_PATH / "Needs_Action"
    if not needs_action.exists():
        return
    count = len([f for f in needs_action.iterdir() if f.suffix == ".md" and not f.name.startswith(".")])
    if count > 0:
        logger.info(f"[MONITOR] {count} item(s) pending in Needs_Action — run /reasoning-loop to process")


# ──────────────────────────────────────────────────────────────────────
# Scheduler class
# ──────────────────────────────────────────────────────────────────────

class Scheduler:
    """Wraps the `schedule` library with AI Employee tasks."""

    def __init__(self, vault_path: str = None):
        global VAULT_PATH
        if vault_path:
            VAULT_PATH = Path(vault_path).resolve()
        self._setup()

    def _setup(self) -> None:
        # Daily dashboard update
        schedule.every().day.at(DAILY_TIME).do(task_daily_dashboard_update)
        logger.info(f"Scheduled: daily dashboard update at {DAILY_TIME}")

        # Full weekly CEO Briefing (Gold Tier: Odoo + tasks + social + logs)
        getattr(schedule.every(), CEO_DAY).at(WEEKLY_AUDIT_TIME).do(task_ceo_briefing)
        logger.info(f"Scheduled: weekly CEO briefing every {CEO_DAY} at {WEEKLY_AUDIT_TIME}")

        # LinkedIn post generation
        getattr(schedule.every(), LINKEDIN_DAY).at(LINKEDIN_TIME).do(task_generate_linkedin_post)
        logger.info(f"Scheduled: LinkedIn post every {LINKEDIN_DAY} at {LINKEDIN_TIME}")

        # Health check every 30 minutes
        schedule.every(30).minutes.do(task_check_needs_action)
        logger.info("Scheduled: Needs_Action check every 30 minutes")

    def run(self) -> None:
        """Blocking scheduler loop."""
        logger.info("Scheduler running...")
        while True:
            schedule.run_pending()
            time.sleep(30)


# ──────────────────────────────────────────────────────────────────────
# CLI (standalone mode)
# ──────────────────────────────────────────────────────────────────────

def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="AI Employee — Scheduler (Gold Tier)")
    parser.add_argument("--vault", default=os.getenv("VAULT_PATH", "AI_Employee_Vault"))
    parser.add_argument("--run-now", choices=["daily", "ceo", "linkedin", "check"],
                        help="Run a specific task immediately then exit")
    args = parser.parse_args()

    if args.run_now:
        VAULT_PATH_local = Path(args.vault).resolve()
        global VAULT_PATH
        VAULT_PATH = VAULT_PATH_local
        tasks = {
            "daily": task_daily_dashboard_update,
            "ceo": task_ceo_briefing,
            "linkedin": task_generate_linkedin_post,
            "check": task_check_needs_action,
        }
        tasks[args.run_now]()
        return

    s = Scheduler(vault_path=args.vault)
    s.run()


if __name__ == "__main__":
    main()
