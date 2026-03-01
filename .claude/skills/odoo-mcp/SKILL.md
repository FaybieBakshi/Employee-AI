# Odoo MCP Skill

Use the Odoo MCP server to query accounting data, list invoices, and
create draft invoices. All financial write actions require human approval.

## When to Use

- User asks for revenue, expenses, or accounting summary
- User wants to list or search invoices
- User wants to create a draft invoice (goes to Pending_Approval)
- User wants to check Odoo connectivity

## Quick Start

### 1. Configure Odoo credentials in .env

```bash
ODOO_URL=http://your-odoo-instance.com
ODOO_DB=your_database_name
ODOO_USER=admin@example.com
ODOO_PASSWORD=your_password
```

### 2. Start the Odoo MCP server

```bash
python -m mcp_servers.odoo_mcp
```

The server registers these tools:
- `get_revenue_summary` — total invoiced, paid, outstanding
- `list_invoices` — paginated invoice list with filters
- `get_expense_summary` — total expenses by category
- `create_draft_invoice` — creates invoice draft (auto-approved)
- `draft_post_invoice` — requests approval to post/confirm an invoice

### 3. Test connectivity

```python
from odoo.client import OdooClient
client = OdooClient()
print(client.ping())            # True if connected
print(client.get_revenue_summary())
```

## Available Tools

| Tool | Type | Description |
|------|------|-------------|
| `get_revenue_summary` | Read | Total invoiced, paid, outstanding |
| `list_invoices` | Read | Paginated invoice list |
| `get_expense_summary` | Read | Total expenses |
| `create_draft_invoice` | Write | Create draft (auto-approved) |
| `draft_post_invoice` | Write | Post invoice (needs HITL approval) |

## Error Handling

- If Odoo is unavailable: `OdooClient.ping()` returns `False` — gracefully skips
- Connection errors use the `odoo` circuit breaker (3 failures → 60s pause)
- Import `from recovery.retry_handler import get_circuit, safe_call`

## HITL Rules

- Reading data: auto-approved
- Creating draft invoices: auto-approved
- Posting/confirming invoices: requires human approval (approval file created in Pending_Approval/)
- Deleting invoices: always requires approval
