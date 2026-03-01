"""
ralph_wiggum.py — Ralph Wiggum Loop Runner (Gold Tier).

The "Ralph Wiggum" pattern keeps Claude Code working until a task is
truly complete:

  1. Set RALPH_* environment variables
  2. Invoke Claude Code with a task prompt
  3. The stop_hook intercepts every exit attempt
  4. Claude continues until it outputs <promise>TASK_COMPLETE</promise>
     OR moves the task file to /Done
  5. Loop up to MAX_ITERATIONS before giving up

Usage:
  python ralph_wiggum.py "Process all emails in Needs_Action"
  python ralph_wiggum.py --max-iterations 5 "Weekly audit"
  python ralph_wiggum.py --task-file AI_Employee_Vault/Needs_Action/EMAIL_abc.md "Process this email"

Environment variables:
  VAULT_PATH          — path to vault (default: AI_Employee_Vault)
  RALPH_MAX_ITERATIONS — max loop iterations (default: 10)
"""

import argparse
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [ralph-wiggum] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("ralph_wiggum")

VAULT_PATH = Path(os.getenv("VAULT_PATH", "AI_Employee_Vault")).resolve()
DEFAULT_MAX_ITERATIONS = int(os.getenv("RALPH_MAX_ITERATIONS", "10"))


def run_loop(
    prompt: str,
    task_file: str = "",
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    dry_run: bool = False,
) -> int:
    """
    Run the Ralph Wiggum loop.

    Sets RALPH_* env vars and invokes Claude Code repeatedly.
    The stop_hook (registered in .claude/settings.json) intercepts
    exit attempts and re-injects the prompt until complete.

    Returns exit code (0 = success / max iterations reached).
    """
    logger.info(f"Starting Ralph Wiggum loop")
    logger.info(f"  Prompt:         {prompt[:80]}{'...' if len(prompt) > 80 else ''}")
    logger.info(f"  Task file:      {task_file or '(none)'}")
    logger.info(f"  Max iterations: {max_iterations}")
    logger.info(f"  Dry run:        {dry_run}")

    if dry_run:
        logger.info("[DRY RUN] Would invoke Claude Code with the above parameters")
        return 0

    # Build environment for the Claude Code subprocess
    env = os.environ.copy()
    env["RALPH_TASK_FILE"] = task_file
    env["RALPH_MAX_ITERATIONS"] = str(max_iterations)
    env["RALPH_PROMPT"] = prompt
    env["RALPH_ITERATION"] = "0"
    env["VAULT_PATH"] = str(VAULT_PATH)

    # Build the full prompt passed to Claude
    full_prompt = (
        f"{prompt}\n\n"
        f"Vault location: {VAULT_PATH}\n\n"
        "Rules:\n"
        "1. Read Company_Handbook.md before acting.\n"
        "2. Process all items in Needs_Action/ (FIFO order).\n"
        "3. Create Plan files in Plans/, move completed items to Done/.\n"
        "4. Update Dashboard.md after each item.\n"
        "5. Write audit logs to Logs/.\n"
        "6. When ALL items are processed, output exactly:\n"
        "   <promise>TASK_COMPLETE</promise>\n"
    )
    if task_file:
        full_prompt += f"\nFocus task file: {task_file}\n"

    logger.info("Invoking Claude Code (stop hook will intercept early exits)...")

    try:
        result = subprocess.run(
            ["claude", "--print", full_prompt],
            env=env,
            cwd=str(VAULT_PATH.parent),
            timeout=max_iterations * 300,  # 5 min per iteration max
        )
        logger.info(f"Claude Code exited with code {result.returncode}")
        return result.returncode

    except FileNotFoundError:
        logger.error("'claude' command not found. Install: npm install -g @anthropic/claude-code")
        return 1
    except subprocess.TimeoutExpired:
        logger.error(f"Timed out after {max_iterations * 300}s")
        return 1
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 130


def run_batch(vault_path: Path = None, max_iterations: int = DEFAULT_MAX_ITERATIONS) -> int:
    """
    Process all items currently in Needs_Action/ using the Ralph Wiggum loop.
    Used by scheduler.py for automatic batch processing.
    """
    vp = vault_path or VAULT_PATH
    needs_action = vp / "Needs_Action"
    if not needs_action.exists():
        logger.warning(f"Needs_Action folder not found: {needs_action}")
        return 0

    pending = sorted(
        [f for f in needs_action.iterdir() if f.suffix == ".md" and not f.name.startswith(".")],
        key=lambda f: f.stat().st_ctime,
    )

    if not pending:
        logger.info("Needs_Action is empty — nothing to process")
        return 0

    logger.info(f"Found {len(pending)} item(s) in Needs_Action/")
    prompt = (
        f"You are the AI Employee. Process all {len(pending)} item(s) in "
        f"{needs_action}. "
        "Work through them oldest-first. For each: read it, create a Plan, "
        "execute auto-approved actions, request approval for sensitive ones, "
        "move to Done. Update Dashboard and write audit logs. "
        "When everything is done, output <promise>TASK_COMPLETE</promise>."
    )

    return run_loop(prompt, max_iterations=max_iterations)


# ──────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="AI Employee — Ralph Wiggum Loop (Gold Tier)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python ralph_wiggum.py "Process all pending emails"
  python ralph_wiggum.py --max-iterations 5 "Run weekly audit"
  python ralph_wiggum.py --task-file AI_Employee_Vault/Needs_Action/EMAIL_abc.md "Handle this email"
  python ralph_wiggum.py --batch   # Process entire Needs_Action queue
        """,
    )
    parser.add_argument("prompt", nargs="?", default="", help="Task prompt for Claude")
    parser.add_argument(
        "--max-iterations", "-n",
        type=int, default=DEFAULT_MAX_ITERATIONS,
        help=f"Max loop iterations (default: {DEFAULT_MAX_ITERATIONS})",
    )
    parser.add_argument(
        "--task-file",
        default="",
        help="Path to the specific task file being processed",
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Process all items in Needs_Action/ automatically",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without invoking Claude",
    )
    parser.add_argument(
        "--vault",
        default=os.getenv("VAULT_PATH", "AI_Employee_Vault"),
        help="Path to the vault",
    )
    args = parser.parse_args()

    global VAULT_PATH
    VAULT_PATH = Path(args.vault).resolve()

    if args.batch:
        sys.exit(run_batch(VAULT_PATH, args.max_iterations))

    if not args.prompt:
        parser.print_help()
        sys.exit(0)

    sys.exit(run_loop(
        prompt=args.prompt,
        task_file=args.task_file,
        max_iterations=args.max_iterations,
        dry_run=args.dry_run,
    ))


if __name__ == "__main__":
    main()
