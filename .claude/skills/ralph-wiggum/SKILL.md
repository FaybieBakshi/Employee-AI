# Ralph Wiggum Skill

Keep Claude working until a task is fully complete using the Stop Hook
persistence pattern. Claude cannot exit until it outputs
`<promise>TASK_COMPLETE</promise>` or moves the task file to /Done.

## When to Use

- User wants Claude to keep working until a multi-step task is done
- Processing a large batch of Needs_Action items without interruption
- Running the weekly audit end-to-end without manual re-prompting
- Any task where "try once and quit" is not acceptable

## How It Works

```
1. ralph_wiggum.py sets RALPH_* environment variables
2. Claude Code is invoked with the task prompt
3. Claude works...
4. Claude tries to exit → stop_hook.py intercepts
5. Hook checks:
   a. Max iterations reached? → allow exit
   b. <promise>TASK_COMPLETE</promise> in transcript? → allow exit
   c. Task file in /Done? → allow exit
   d. Needs_Action empty? → allow exit
   e. None of the above → BLOCK exit, re-inject original prompt
6. Claude continues working
7. Repeat until complete or max_iterations reached
```

## Quick Start

```bash
# Process a single task
python ralph_wiggum.py "Process the email in Needs_Action"

# Process entire queue
python ralph_wiggum.py --batch

# Limit iterations
python ralph_wiggum.py --max-iterations 5 "Run weekly audit"

# Dry run (see what would happen)
python ralph_wiggum.py --dry-run "Test prompt"
```

## Completing a Task

From inside Claude Code, signal completion with:

```
<promise>TASK_COMPLETE</promise>
```

OR by moving the task file to `/Done`:

```bash
mv AI_Employee_Vault/Needs_Action/TASK_abc.md AI_Employee_Vault/Done/TASK_abc.md
```

## Configuration

The stop hook is registered in `.claude/settings.json`:
```json
{
  "hooks": {
    "Stop": [{"matcher": "", "hooks": [{"type": "command", "command": "python hooks/stop_hook.py"}]}]
  }
}
```

Environment variables:
```bash
RALPH_MAX_ITERATIONS=10    # How many times to retry (default: 10)
RALPH_TASK_FILE=           # Path to the active task file
RALPH_PROMPT=              # Original prompt (auto-re-injected)
RALPH_ITERATION=0          # Current iteration count (auto-incremented)
```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Hook not triggering | Check `.claude/settings.json` exists and is valid JSON |
| Infinite loop | Check that task files are being moved to /Done correctly |
| Max iterations too low | Set `RALPH_MAX_ITERATIONS=20` in .env |
| Hook blocking unexpectedly | Check Needs_Action/ — items may still be pending |
