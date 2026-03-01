"""
client.py — Odoo Community JSON-RPC client (Gold Tier).

Implements Odoo's External API using JSON-RPC 2.0:
  - authenticate()     → get uid
  - search_read()      → query model records
  - create()           → create a record (draft)
  - write()            → update a record
  - execute_kw()       → generic model method call

Supports Odoo 17+ (Community or Enterprise).

Environment variables (.env):
  ODOO_URL       — e.g. http://localhost:8069
  ODOO_DB        — database name
  ODOO_USER      — login email
  ODOO_PASSWORD  — password (or API key for Odoo 16+)
"""

import json
import os
import urllib.request
import urllib.error
from typing import Any

from dotenv import load_dotenv

load_dotenv()


class OdooClient:
    """
    Thin JSON-RPC client for Odoo's External API.
    Reference: https://www.odoo.com/documentation/17.0/developer/reference/external_api.html
    """

    def __init__(
        self,
        url: str = None,
        db: str = None,
        username: str = None,
        password: str = None,
    ):
        self.url = (url or os.getenv("ODOO_URL", "http://localhost:8069")).rstrip("/")
        self.db = db or os.getenv("ODOO_DB", "")
        self.username = username or os.getenv("ODOO_USER", "")
        self.password = password or os.getenv("ODOO_PASSWORD", "")
        self._uid: int | None = None
        self._req_id = 0

    # ------------------------------------------------------------------
    # Low-level JSON-RPC
    # ------------------------------------------------------------------

    def _rpc(self, endpoint: str, params: dict) -> Any:
        """Send a JSON-RPC 2.0 request and return the result."""
        self._req_id += 1
        payload = json.dumps({
            "jsonrpc": "2.0",
            "method": "call",
            "id": self._req_id,
            "params": params,
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{self.url}{endpoint}",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            raise ConnectionError(f"HTTP {err.code}: {err.read().decode()}")
        except Exception as err:
            raise ConnectionError(f"Odoo connection error: {err}")

        if "error" in result:
            msg = result["error"].get("data", {}).get("message", result["error"].get("message", "Unknown"))
            raise RuntimeError(f"Odoo RPC error: {msg}")

        return result.get("result")

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def authenticate(self) -> int:
        """Authenticate and return uid. Caches uid for session reuse."""
        if self._uid:
            return self._uid

        if not self.db or not self.username or not self.password:
            raise ValueError("ODOO_DB, ODOO_USER, and ODOO_PASSWORD must be set in .env")

        uid = self._rpc("/web/dataset/call_kw", {
            "model": "res.users",
            "method": "authenticate",
            "args": [self.db, self.username, self.password, {}],
            "kwargs": {},
        })

        # Fallback to /web/session/authenticate for older Odoo versions
        if not uid:
            result = self._rpc("/web/session/authenticate", {
                "db": self.db,
                "login": self.username,
                "password": self.password,
            })
            uid = result.get("uid") if isinstance(result, dict) else None

        if not uid:
            raise PermissionError("Odoo authentication failed — check credentials")

        self._uid = uid
        return uid

    # ------------------------------------------------------------------
    # Model operations
    # ------------------------------------------------------------------

    def execute_kw(self, model: str, method: str, args: list, kwargs: dict = None) -> Any:
        """Generic execute_kw — the core of Odoo's external API."""
        uid = self.authenticate()
        return self._rpc("/web/dataset/call_kw", {
            "model": model,
            "method": method,
            "args": [self.db, uid, self.password] + args,
            "kwargs": kwargs or {},
        })

    def search_read(
        self,
        model: str,
        domain: list = None,
        fields: list = None,
        limit: int = 80,
        order: str = "",
    ) -> list[dict]:
        """Search and read records from a model."""
        return self.execute_kw(model, "search_read", [domain or []], {
            "fields": fields or [],
            "limit": limit,
            "order": order,
        })

    def create(self, model: str, values: dict) -> int:
        """Create a record and return its ID."""
        return self.execute_kw(model, "create", [values])

    def write(self, model: str, ids: list[int], values: dict) -> bool:
        """Update records by ID."""
        return self.execute_kw(model, "write", [ids, values])

    def search(self, model: str, domain: list, limit: int = 80) -> list[int]:
        """Return record IDs matching domain."""
        return self.execute_kw(model, "search", [domain], {"limit": limit})

    # ------------------------------------------------------------------
    # Convenience methods
    # ------------------------------------------------------------------

    def get_invoices(self, state: str = "posted", limit: int = 50) -> list[dict]:
        """Get invoices (account.move of type out_invoice)."""
        domain = [("move_type", "=", "out_invoice")]
        if state:
            domain.append(("state", "=", state))
        return self.search_read(
            "account.move",
            domain=domain,
            fields=["name", "partner_id", "amount_total", "state", "invoice_date", "invoice_date_due"],
            limit=limit,
            order="invoice_date desc",
        )

    def get_revenue_summary(self) -> dict:
        """Aggregate revenue from posted invoices."""
        invoices = self.get_invoices(state="posted", limit=200)
        total = sum(inv.get("amount_total", 0) for inv in invoices)
        paid = self.search_read(
            "account.move",
            domain=[("move_type", "=", "out_invoice"), ("payment_state", "=", "paid")],
            fields=["amount_total"],
            limit=200,
        )
        paid_total = sum(inv.get("amount_total", 0) for inv in paid)

        return {
            "total_invoiced": round(total, 2),
            "total_paid": round(paid_total, 2),
            "outstanding": round(total - paid_total, 2),
            "invoice_count": len(invoices),
            "paid_count": len(paid),
        }

    def create_draft_invoice(self, partner_id: int, lines: list[dict]) -> int:
        """
        Create a draft invoice (does NOT post it — requires human approval).
        lines: [{"name": "Service", "quantity": 1, "price_unit": 100.0}]
        """
        invoice_data = {
            "move_type": "out_invoice",
            "partner_id": partner_id,
            "state": "draft",
            "invoice_line_ids": [
                (0, 0, {
                    "name": line["name"],
                    "quantity": line.get("quantity", 1),
                    "price_unit": line.get("price_unit", 0),
                })
                for line in lines
            ],
        }
        return self.create("account.move", invoice_data)

    def get_expense_summary(self) -> dict:
        """Get vendor bill (expense) summary."""
        bills = self.search_read(
            "account.move",
            domain=[("move_type", "=", "in_invoice"), ("state", "=", "posted")],
            fields=["amount_total", "partner_id"],
            limit=200,
        )
        total = sum(b.get("amount_total", 0) for b in bills)
        return {
            "total_expenses": round(total, 2),
            "bill_count": len(bills),
        }

    def ping(self) -> bool:
        """Test connectivity to Odoo server."""
        try:
            self.authenticate()
            return True
        except Exception:
            return False
