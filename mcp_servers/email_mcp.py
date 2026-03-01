"""
email_mcp.py — Email MCP Server for the AI Employee (Silver Tier).

Exposes two tools to Claude Code via the Model Context Protocol:
  send_email   — Sends an email via SMTP (requires HITL approval in vault)
  draft_email  — Saves a draft to /Pending_Approval (safe, no sending)

This server runs over stdio (standard MCP transport) and is registered
in .mcp.json so Claude Code can call it directly.

Setup:
  1. Copy .env.example to .env and fill in SMTP_* variables
  2. For Gmail: enable 2FA and create an App Password at
     myaccount.google.com/apppasswords
  3. Register in .mcp.json (already done in this project)

Usage (Claude Code calls this automatically via .mcp.json):
  python -m mcp_servers.email_mcp

Manual test:
  echo '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | python -m mcp_servers.email_mcp

Environment variables (.env):
  SMTP_HOST       — e.g. smtp.gmail.com (default)
  SMTP_PORT       — e.g. 587 (default, TLS)
  SMTP_USER       — sender email address
  SMTP_PASSWORD   — app password (NOT your main password)
  VAULT_PATH      — path to vault (for draft_email)
  DRY_RUN         — if "true", logs actions without sending
"""

import json
import logging
import os
import smtplib
import sys
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
logger = logging.getLogger("email_mcp")

# ──────────────────────────────────────────────────────────────────────
# MCP Server — minimal stdio JSON-RPC 2.0 implementation
# ──────────────────────────────────────────────────────────────────────

SERVER_INFO = {
    "name": "email-mcp",
    "version": "1.0.0",
    "description": "Send and draft emails via SMTP — AI Employee Silver Tier",
}

TOOLS = [
    {
        "name": "send_email",
        "description": (
            "Send an email via SMTP. "
            "IMPORTANT: Only call this after the human has approved the action "
            "by moving the draft file to /Approved in the vault."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address"},
                "subject": {"type": "string", "description": "Email subject line"},
                "body": {"type": "string", "description": "Plain text email body"},
                "cc": {"type": "string", "description": "CC email address (optional)", "default": ""},
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "draft_email",
        "description": (
            "Save an email draft to /Pending_Approval in the vault. "
            "Safe to call without approval — does NOT send. "
            "The human must move the file to /Approved before it is sent."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address"},
                "subject": {"type": "string", "description": "Email subject line"},
                "body": {"type": "string", "description": "Plain text email body"},
                "reason": {"type": "string", "description": "Why this email needs to be sent"},
            },
            "required": ["to", "subject", "body"],
        },
    },
]


# ──────────────────────────────────────────────────────────────────────
# Tool implementations
# ──────────────────────────────────────────────────────────────────────

def _send_email(to: str, subject: str, body: str, cc: str = "") -> str:
    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER", "")
    smtp_pass = os.getenv("SMTP_PASSWORD", "")
    dry_run = os.getenv("DRY_RUN", "true").lower() == "true"

    if not smtp_user or not smtp_pass:
        return "ERROR: SMTP_USER or SMTP_PASSWORD not configured in .env"

    if dry_run:
        return (
            f"[DRY RUN] Would send email:\n"
            f"  To: {to}\n"
            f"  Subject: {subject}\n"
            f"  Body: {body[:200]}..."
        )

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = smtp_user
        msg["To"] = to
        if cc:
            msg["Cc"] = cc
        msg.attach(MIMEText(body, "plain"))

        recipients = [to] + ([cc] if cc else [])
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.ehlo()
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, recipients, msg.as_string())

        return f"Email sent successfully to {to!r} | Subject: {subject!r}"
    except smtplib.SMTPException as err:
        return f"SMTP error: {err}"
    except Exception as err:
        return f"Error sending email: {err}"


def _draft_email(to: str, subject: str, body: str, reason: str = "") -> str:
    vault_path = Path(os.getenv("VAULT_PATH", "AI_Employee_Vault")).resolve()
    pending = vault_path / "Pending_Approval"
    pending.mkdir(parents=True, exist_ok=True)

    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y-%m-%d_%H%M")
    safe_subject = subject[:40].replace(" ", "_").replace("/", "-")
    filename = f"APPROVAL_email_{date_str}_{safe_subject}.md"
    filepath = pending / filename

    content = f"""---
type: approval_request
action: send_email
to: "{to}"
subject: "{subject}"
created: {now.isoformat()}
reason: "{reason}"
status: pending
---

## Email Draft — Pending Approval

| Field   | Value |
|---------|-------|
| To      | {to} |
| Subject | {subject} |
| Reason  | {reason or "Not specified"} |

### Body

{body}

---

## To Approve

Move this file to `AI_Employee_Vault/Approved/` — the Approval Watcher will send it.

## To Reject

Move this file to `AI_Employee_Vault/Rejected/`.

## To Edit

Edit the **Body** section above before approving.
"""
    filepath.write_text(content, encoding="utf-8")
    return (
        f"Draft saved to: {filepath.name}\n"
        f"Review at: {filepath}\n"
        f"Approve by moving to /Approved, reject by moving to /Rejected."
    )


# ──────────────────────────────────────────────────────────────────────
# JSON-RPC 2.0 stdio loop
# ──────────────────────────────────────────────────────────────────────

def _respond(request_id, result=None, error=None):
    response = {"jsonrpc": "2.0", "id": request_id}
    if error:
        response["error"] = error
    else:
        response["result"] = result
    sys.stdout.write(json.dumps(response) + "\n")
    sys.stdout.flush()


def _handle(request: dict) -> None:
    method = request.get("method", "")
    req_id = request.get("id")
    params = request.get("params", {})

    if method == "initialize":
        _respond(req_id, {
            "protocolVersion": "2024-11-05",
            "serverInfo": SERVER_INFO,
            "capabilities": {"tools": {}},
        })

    elif method == "tools/list":
        _respond(req_id, {"tools": TOOLS})

    elif method == "tools/call":
        tool_name = params.get("name", "")
        args = params.get("arguments", {})

        try:
            if tool_name == "send_email":
                result_text = _send_email(
                    to=args["to"],
                    subject=args["subject"],
                    body=args["body"],
                    cc=args.get("cc", ""),
                )
            elif tool_name == "draft_email":
                result_text = _draft_email(
                    to=args["to"],
                    subject=args["subject"],
                    body=args["body"],
                    reason=args.get("reason", ""),
                )
            else:
                _respond(req_id, error={"code": -32601, "message": f"Unknown tool: {tool_name}"})
                return

            _respond(req_id, {
                "content": [{"type": "text", "text": result_text}],
                "isError": result_text.startswith("ERROR"),
            })

        except KeyError as err:
            _respond(req_id, error={"code": -32602, "message": f"Missing required argument: {err}"})
        except Exception as err:
            _respond(req_id, error={"code": -32603, "message": str(err)})

    elif method == "notifications/initialized":
        pass  # No response needed for notifications

    else:
        if req_id is not None:
            _respond(req_id, error={"code": -32601, "message": f"Method not found: {method}"})


def main() -> None:
    """Run the MCP server — reads JSON-RPC requests from stdin, writes responses to stdout."""
    logger.info("Email MCP server starting (stdio transport)")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            _handle(request)
        except json.JSONDecodeError as err:
            sys.stdout.write(json.dumps({
                "jsonrpc": "2.0", "id": None,
                "error": {"code": -32700, "message": f"Parse error: {err}"}
            }) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
