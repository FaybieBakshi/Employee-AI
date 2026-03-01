"""
post_generator.py — Generates LinkedIn post content from vault data (Silver Tier).

Reads:
  - AI_Employee_Vault/Company_Handbook.md  → business name, goals
  - AI_Employee_Vault/Dashboard.md         → recent activity
  - AI_Employee_Vault/Done/                → completed tasks this week

Generates a professional LinkedIn post and saves it to:
  - AI_Employee_Vault/Pending_Approval/LINKEDIN_<date>.md

The Approval Watcher then waits for human approval before posting.

Usage:
  python -m linkedin.post_generator
  python -m linkedin.post_generator --topic "product launch"
  python -m linkedin.post_generator --template insight

Templates:
  insight    — Share a business insight or lesson learned
  milestone  — Celebrate a completed project or goal
  tips       — Share tips relevant to your industry
  story      — Behind-the-scenes story about the work

Environment variables (.env):
  VAULT_PATH          — path to vault
  LINKEDIN_BUSINESS   — business name (overrides handbook)
  LINKEDIN_INDUSTRY   — your industry (e.g. "software consulting")
  LINKEDIN_TONE       — professional | conversational | inspirational (default: professional)
"""

import argparse
import os
import re
import textwrap
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


# ──────────────────────────────────────────────────────────────────────
# Vault reader helpers
# ──────────────────────────────────────────────────────────────────────

def _read_file_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, PermissionError):
        return ""


def _extract_business_name(handbook_text: str) -> str:
    match = re.search(r"Business Name\s*:\s*(.+)", handbook_text)
    if match:
        name = match.group(1).strip()
        if name and "update this" not in name.lower():
            return name
    return os.getenv("LINKEDIN_BUSINESS", "Our Business")


def _extract_recent_done(done_dir: Path, max_items: int = 5) -> list[str]:
    """Return names of most recently completed tasks."""
    files = sorted(
        [f for f in done_dir.iterdir() if f.suffix == ".md" and not f.name.startswith(".")],
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    items = []
    for f in files[:max_items]:
        # Try to extract a human-readable name from the file
        text = _read_file_safe(f)
        subject_match = re.search(r"^## Objective\s*\n(.+)", text, re.MULTILINE)
        if subject_match:
            items.append(subject_match.group(1).strip())
        else:
            items.append(f.stem.replace("_", " ").replace("Plan ", "").replace("FILE ", ""))
    return items


# ──────────────────────────────────────────────────────────────────────
# Post templates
# ──────────────────────────────────────────────────────────────────────

def _template_insight(business: str, industry: str, tone: str, done_items: list[str]) -> str:
    recent = done_items[0] if done_items else "a client project"
    return textwrap.dedent(f"""
    Working on {recent} this week reminded me of something important in {industry}:

    The details that seem small at the planning stage are often the ones that matter most at delivery.

    At {business}, we've been doubling down on process — not because we love paperwork, but because consistency is what lets a small team punch above its weight.

    What's one process improvement that made a real difference for your team?

    #productivity #{industry.replace(' ', '')} #business #operations
    """).strip()


def _template_milestone(business: str, industry: str, tone: str, done_items: list[str]) -> str:
    milestones = "\n".join(f"✅ {item}" for item in done_items) if done_items else "✅ Key deliverable completed"
    return textwrap.dedent(f"""
    Proud of what the team accomplished this week at {business}:

    {milestones}

    Every completed task is a promise kept. That's what builds trust with clients.

    If you're looking for a reliable partner in {industry}, let's connect.

    #milestone #{industry.replace(' ', '')} #clientsuccess #growth
    """).strip()


def _template_tips(business: str, industry: str, tone: str, done_items: list[str]) -> str:
    return textwrap.dedent(f"""
    3 things I wish I'd known earlier in {industry}:

    1️⃣ Clarity beats cleverness — simple systems scale, complex ones break.
    2️⃣ Your best clients come from your happiest current clients. Invest there first.
    3️⃣ Speed of response is itself a product. Being quick builds confidence.

    At {business} we've learned these the hard way so you don't have to.

    Which one resonates most with you?

    #{industry.replace(' ', '')} #businesstips #entrepreneurship
    """).strip()


def _template_story(business: str, industry: str, tone: str, done_items: list[str]) -> str:
    recent = done_items[0] if done_items else "a recent project"
    return textwrap.dedent(f"""
    A quick story from behind the scenes at {business}:

    Last week, wrapping up {recent}, we hit an unexpected roadblock.

    Instead of pushing through with the original plan, we paused, re-scoped, and found a simpler path.

    It took two extra hours. It saved the client two weeks.

    In {industry}, knowing when to adapt is just as valuable as knowing the plan.

    What's a recent pivot that turned out better than the original path?

    #behindthescenes #{industry.replace(' ', '')} #agile #problemsolving
    """).strip()


TEMPLATES = {
    "insight": _template_insight,
    "milestone": _template_milestone,
    "tips": _template_tips,
    "story": _template_story,
}


# ──────────────────────────────────────────────────────────────────────
# Main generator
# ──────────────────────────────────────────────────────────────────────

def generate_post(
    vault_path: str,
    template: str = "insight",
    topic: str = "",
) -> Path:
    """
    Generate a LinkedIn post and save to /Pending_Approval.
    Returns the path to the approval request file.
    """
    vault = Path(vault_path).resolve()
    pending_approval = vault / "Pending_Approval"
    done_dir = vault / "Done"
    pending_approval.mkdir(parents=True, exist_ok=True)

    # Read vault context
    handbook_text = _read_file_safe(vault / "Company_Handbook.md")
    business = _extract_business_name(handbook_text)
    industry = os.getenv("LINKEDIN_INDUSTRY", "business")
    tone = os.getenv("LINKEDIN_TONE", "professional")
    done_items = _extract_recent_done(done_dir)

    # Generate post content
    fn = TEMPLATES.get(template, _template_insight)
    post_content = fn(business, industry, tone, done_items)

    # If custom topic provided, prepend it
    if topic:
        post_content = f"[Topic: {topic}]\n\n" + post_content

    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d")
    filename = f"LINKEDIN_{date_str}_{template}.md"
    filepath = pending_approval / filename

    approval_file = f"""---
type: approval_request
action: post_linkedin
template: {template}
business: "{business}"
industry: "{industry}"
created: {now.isoformat()}
status: pending
---

## LinkedIn Post — Pending Approval

**Template:** {template}
**Business:** {business}
**Date:** {date_str}

---

### Post Content

{post_content}

---

## To Approve

Move this file to `AI_Employee_Vault/Approved/` — the Approval Watcher will post it to LinkedIn.

## To Reject

Move this file to `AI_Employee_Vault/Rejected/` — it will be archived without posting.

## To Edit

Edit the **Post Content** section above before moving to Approved.
"""

    filepath.write_text(approval_file, encoding="utf-8")
    return filepath


# ──────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="AI Employee — LinkedIn Post Generator (Silver Tier)"
    )
    parser.add_argument("--vault", default=os.getenv("VAULT_PATH", "AI_Employee_Vault"))
    parser.add_argument(
        "--template",
        choices=list(TEMPLATES.keys()),
        default="insight",
        help="Post template to use (default: insight)",
    )
    parser.add_argument(
        "--topic",
        default="",
        help="Optional custom topic to include in the post",
    )
    args = parser.parse_args()

    vault = Path(args.vault).resolve()
    if not vault.exists():
        print(f"ERROR: Vault not found: {vault}")
        raise SystemExit(1)

    filepath = generate_post(str(vault), template=args.template, topic=args.topic)
    print(f"LinkedIn post generated: {filepath}")
    print(f"Review and move to Approved/ to post, or Rejected/ to discard.")
    print(f"\nPost preview:")
    print("-" * 60)
    # Print just the post content section
    text = filepath.read_text(encoding="utf-8")
    in_content = False
    for line in text.splitlines():
        if line.strip() == "### Post Content":
            in_content = True
            continue
        if in_content and line.startswith("---"):
            break
        if in_content:
            print(line)


if __name__ == "__main__":
    main()
