"""
stop_hook.py — Ralph Wiggum Stop Hook for Claude Code (Gold Tier).

Called by Claude Code whenever it attempts to stop/exit a session.
Implements the "Ralph Wiggum" persistence pattern:

  1. Claude works on a task
  2. Claude tries to exit
  3. This hook intercepts the exit
  4. Checks: is the active task file in /Done ?
     - YES → allow exit (task complete)
     - NO  → block exit, re-inject the original prompt
  5. Claude continues working
  6. Repeat until max_iterations or task moves to /Done

Two completion strategies:
  Promise-based: Claude outputs <promise>TASK_COMPLETE</promise>
  File-based:    Task file is physically moved to /Done (more reliable)

Hook input (via stdin, JSON):
  {
    "session_id": "...",
    "transcript_path": "...",
    "stop_hook_active": true
  }

Hook output (stdout, JSON):
  Block exit:  {"decision": "block", "reason": "Task not complete"}
  Allow exit:  exit code 0 (no output needed)

Reference: https://github.com/anthropics/claude-code/tree/main/.claude/plugins/ralph-wiggum

Environment variables:
  VAULT_PATH          — path to vault
  RALPH_MAX_ITERATIONS — max loop iterations (default: 10)
  RALPH_TASK_FILE     — path to active task state file (set by ralph_wiggum.py)
  RALPH_ITERATION     — current iteration count (set by ralph_wiggum.py)
  RALPH_PROMPT        — the original task prompt (set by ralph_wiggum.py)
"""

import json
import os
import sys
from pathlib import Path


VAULT_PATH = Path(os.getenv("VAULT_PATH", "AI_Employee_Vault")).resolve()
MAX_ITERATIONS = int(os.getenv("RALPH_MAX_ITERATIONS", "10"))
TASK_FILE = os.getenv("RALPH_TASK_FILE", "")
ITERATION = int(os.getenv("RALPH_ITERATION", "0"))
PROMPT = os.getenv("RALPH_PROMPT", "")


def _read_stdin() -> dict:
    """Read JSON input from stdin (Claude Code hook protocol)."""
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _check_promise_in_transcript(transcript_path: str) -> bool:
    """Check if Claude output the TASK_COMPLETE promise in its last response."""
    if not transcript_path:
        return False
    try:
        text = Path(transcript_path).read_text(encoding="utf-8")
        return "<promise>TASK_COMPLETE</promise>" in text
    except OSError:
        return False


def _check_task_file_done() -> bool:
    """Check if the active task file has been moved to /Done (file-movement strategy)."""
    if not TASK_FILE:
        return False
    task_path = Path(TASK_FILE)
    task_name = task_path.name

    # Check if it exists in /Done
    done_path = VAULT_PATH / "Done" / task_name
    return done_path.exists()


def _block(reason: str) -> None:
    """Block Claude from exiting — outputs JSON to stdout."""
    response = {
        "decision": "block",
        "reason": reason,
    }
    sys.stdout.write(json.dumps(response) + "\n")
    sys.stdout.flush()


def main() -> None:
    hook_input = _read_stdin()
    transcript_path = hook_input.get("transcript_path", "")

    # Guard: max iterations
    if ITERATION >= MAX_ITERATIONS:
        # Allow exit — max iterations reached
        sys.stderr.write(f"[ralph-wiggum] Max iterations ({MAX_ITERATIONS}) reached — allowing exit\n")
        sys.exit(0)

    # Check promise-based completion
    if _check_promise_in_transcript(transcript_path):
        sys.stderr.write("[ralph-wiggum] TASK_COMPLETE promise detected — allowing exit\n")
        sys.exit(0)

    # Check file-movement completion
    if _check_task_file_done():
        sys.stderr.write(f"[ralph-wiggum] Task file found in /Done — allowing exit\n")
        sys.exit(0)

    # Check if Needs_Action is empty (all tasks processed)
    needs_action = VAULT_PATH / "Needs_Action"
    if needs_action.exists():
        pending = [f for f in needs_action.iterdir() if f.suffix == ".md" and not f.name.startswith(".")]
        if not pending and not TASK_FILE:
            sys.stderr.write("[ralph-wiggum] Needs_Action is empty — allowing exit\n")
            sys.exit(0)

    # Task not complete — block exit and re-inject prompt
    iteration_label = f"[Iteration {ITERATION + 1}/{MAX_ITERATIONS}]"
    if PROMPT:
        reason = (
            f"{iteration_label} Task not yet complete. Continue working.\n\n"
            f"Original task: {PROMPT}\n\n"
            f"Check /Needs_Action for remaining items. "
            f"Output <promise>TASK_COMPLETE</promise> when ALL items are processed and in /Done."
        )
    else:
        reason = (
            f"{iteration_label} Task not yet complete. "
            f"Continue processing /Needs_Action items until all are moved to /Done. "
            f"Output <promise>TASK_COMPLETE</promise> when finished."
        )

    sys.stderr.write(f"[ralph-wiggum] Iteration {ITERATION + 1} — blocking exit, re-injecting prompt\n")
    _block(reason)


if __name__ == "__main__":
    main()
