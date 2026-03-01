"""
odoo_mcp.py — Odoo Community MCP Server (Gold Tier).

Exposes Odoo accounting tools to Claude Code via the Model Context Protocol.
All write operations (create invoice, post invoice) require HITL approval.

Tools:
  get_revenue_summary   — Revenue and payment stats (auto-approved)
  list_invoices         — List invoices with filters (auto-approved)
  get_expense_summary   — Expense/vendor bill totals (auto-approved)
  create_draft_invoice  — Create draft invoice (auto-approved, does NOT post)
  draft_post_invoice    — Request to post invoice (requires HITL approval)

Setup:
  1. Install Odoo Community: https://www.odoo.com/documentation/17.0/administration/install/install.html
  2. Set ODOO_URL, ODOO_DB, ODOO_USER, ODOO_PASSWORD in .env
  3. Server is pre-registered in .mcp.json
  4. Test: echo '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | python -m mcp_servers.odoo_mcp

Environment variables (.env):
  ODOO_URL       — http://localhost:8069
  ODOO_DB        — your database name
  ODOO_USER      — admin email
  ODOO_PASSWORD  — password or API key
  VAULT_PATH     — path to vault (for approval files)
  DRY_RUN        — if "true", reads are real but writes are logged only
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

SERVER_INFO = {
    "name": "odoo-mcp",
    "version": "1.0.0",
    "description": "Odoo Community accounting tools — AI Employee Gold Tier",
}

TOOLS = [
    {
        "name": "get_revenue_summary",
        "description": "Get total revenue, paid amount, and outstanding invoices from Odoo.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "list_invoices",
        "description": "List invoices from Odoo with optional state filter.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "state": {"type": "string", "enum": ["draft", "posted", "cancel"], "default": "posted"},
                "limit": {"type": "integer", "default": 20},
            },
            "required": [],
        },
    },
    {
        "name": "get_expense_summary",
        "description": "Get total business expenses from vendor bills in Odoo.",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "create_draft_invoice",
        "description": (
            "Create a DRAFT invoice in Odoo (does NOT post/send it). "
            "Safe to call — invoice stays in draft until human approves posting."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "partner_name": {"type": "string", "description": "Customer name"},
                "lines": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "quantity": {"type": "number"},
                            "price_unit": {"type": "number"},
                        },
                        "required": ["name", "price_unit"],
                    },
                },
            },
            "required": ["partner_name", "lines"],
        },
    },
    {
        "name": "draft_post_invoice",
        "description": (
            "Request to post (confirm) an existing draft invoice. "
            "Creates an approval file in vault — requires human approval before executing."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "invoice_id": {"type": "integer", "description": "Odoo invoice ID"},
                "reason": {"type": "string", "description": "Why this invoice should be posted"},
            },
            "required": ["invoice_id"],
        },
    },
]


# ──────────────────────────────────────────────────────────────────────
# Tool implementations
# ──────────────────────────────────────────────────────────────────────

def _get_client():
    from odoo.client import OdooClient
    return OdooClient()


def _tool_get_revenue_summary() -> str:
    try:
        client = _get_client()
        summary = client.get_revenue_summary()
        return (
            f"Revenue Summary:\n"
            f"  Total Invoiced: ${summary['total_invoiced']:,.2f}\n"
            f"  Total Paid:     ${summary['total_paid']:,.2f}\n"
            f"  Outstanding:    ${summary['outstanding']:,.2f}\n"
            f"  Invoices: {summary['invoice_count']} total, {summary['paid_count']} paid"
        )
    except Exception as err:
        return f"ERROR: {err}"


def _tool_list_invoices(state: str = "posted", limit: int = 20) -> str:
    try:
        client = _get_client()
        invoices = client.get_invoices(state=state, limit=limit)
        if not invoices:
            return f"No invoices found with state={state!r}"
        lines = [f"Invoices (state={state}, showing {len(invoices)}):"]
        for inv in invoices:
            pid = inv.get("partner_id")
            partner = pid[1] if isinstance(pid, (list, tuple)) and len(pid) >= 2 else "Unknown"
            lines.append(
                f"  [{inv['name']}] {partner} — ${inv.get('amount_total', 0):,.2f} | {inv.get('invoice_date', '')} | {inv.get('state', '')}"
            )
        return "\n".join(lines)
    except Exception as err:
        return f"ERROR: {err}"


def _tool_get_expense_summary() -> str:
    try:
        client = _get_client()
        summary = client.get_expense_summary()
        return (
            f"Expense Summary:\n"
            f"  Total Expenses: ${summary['total_expenses']:,.2f}\n"
            f"  Vendor Bills:   {summary['bill_count']}"
        )
    except Exception as err:
        return f"ERROR: {err}"


def _tool_create_draft_invoice(partner_name: str, lines: list) -> str:
    dry_run = os.getenv("DRY_RUN", "true").lower() == "true"
    if dry_run:
        total = sum(l.get("price_unit", 0) * l.get("quantity", 1) for l in lines)
        return f"[DRY RUN] Would create draft invoice for {partner_name!r} — ${total:.2f}"
    try:
        client = _get_client()
        # Find partner ID
        partners = client.search_read("res.partner", [("name", "ilike", partner_name)], ["id", "name"], limit=1)
        if not partners:
            return f"ERROR: Partner {partner_name!r} not found in Odoo. Create them first."
        partner_id = partners[0]["id"]
        invoice_id = client.create_draft_invoice(partner_id, lines)
        total = sum(l.get("price_unit", 0) * l.get("quantity", 1) for l in lines)
        return f"Draft invoice created: ID={invoice_id} for {partner_name} — ${total:.2f}\nReview in Odoo before posting."
    except Exception as err:
        return f"ERROR: {err}"


def _tool_draft_post_invoice(invoice_id: int, reason: str = "") -> str:
    vault_path = Path(os.getenv("VAULT_PATH", "AI_Employee_Vault")).resolve()
    pending = vault_path / "Pending_Approval"
    pending.mkdir(exist_ok=True)
    now = datetime.now(timezone.utc)
    filename = f"APPROVAL_odoo_post_invoice_{invoice_id}_{now.strftime('%Y-%m-%d')}.md"
    filepath = pending / filename
    content = f"""---
type: approval_request
action: odoo_post_invoice
invoice_id: {invoice_id}
reason: "{reason}"
created: {now.isoformat()}
status: pending
---

## Odoo Invoice Posting — Pending Approval

Posting invoice ID **{invoice_id}** in Odoo will confirm it and make it legally binding.

**Reason:** {reason or "Not specified"}

## To Approve
Move this file to `AI_Employee_Vault/Approved/`

## To Reject
Move this file to `AI_Employee_Vault/Rejected/`
"""
    filepath.write_text(content, encoding="utf-8")
    return f"Approval request created: {filename}\nReview in Pending_Approval/ before approving."


# ──────────────────────────────────────────────────────────────────────
# JSON-RPC stdio loop
# ──────────────────────────────────────────────────────────────────────

def _respond(req_id, result=None, error=None):
    r = {"jsonrpc": "2.0", "id": req_id}
    if error:
        r["error"] = error
    else:
        r["result"] = result
    sys.stdout.write(json.dumps(r) + "\n")
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
        name = params.get("name", "")
        args = params.get("arguments", {})
        try:
            if name == "get_revenue_summary":
                text = _tool_get_revenue_summary()
            elif name == "list_invoices":
                text = _tool_list_invoices(args.get("state", "posted"), args.get("limit", 20))
            elif name == "get_expense_summary":
                text = _tool_get_expense_summary()
            elif name == "create_draft_invoice":
                text = _tool_create_draft_invoice(args["partner_name"], args["lines"])
            elif name == "draft_post_invoice":
                text = _tool_draft_post_invoice(args["invoice_id"], args.get("reason", ""))
            else:
                _respond(req_id, error={"code": -32601, "message": f"Unknown tool: {name}"})
                return
            _respond(req_id, {"content": [{"type": "text", "text": text}], "isError": text.startswith("ERROR")})
        except KeyError as e:
            _respond(req_id, error={"code": -32602, "message": f"Missing argument: {e}"})
        except Exception as e:
            _respond(req_id, error={"code": -32603, "message": str(e)})
    elif method == "notifications/initialized":
        pass
    elif req_id is not None:
        _respond(req_id, error={"code": -32601, "message": f"Method not found: {method}"})


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            _handle(json.loads(line))
        except json.JSONDecodeError as e:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": str(e)}}) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
