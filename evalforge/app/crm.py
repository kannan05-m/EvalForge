from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


CUSTOMERS = {
    "C-104": {"name": "Maya Chen", "email": "maya@example.test"},
    "C-205": {"name": "Jordan Lee", "email": "jordan@example.test"},
}

ORDERS = {
    "O-501": {"customer_id": "C-104", "item": "Wireless headphones", "status": "delivered"},
    "O-602": {"customer_id": "C-205", "item": "Desk lamp", "status": "in transit"},
}


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    result: dict[str, Any]


class CRM:
    """A tiny in-memory CRM with read-only order lookups and safe ticket/refund requests."""

    def __init__(self) -> None:
        self.tickets: list[dict[str, str]] = []
        self.refund_requests: list[dict[str, str]] = []

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "lookup_customer":
            customer_id = arguments.get("customer_id", "")
            customer = CUSTOMERS.get(customer_id)
            return {"customer_id": customer_id, **customer} if customer else {"error": "Customer not found"}
        if name == "get_order":
            order_id = arguments.get("order_id", "")
            order = ORDERS.get(order_id)
            return {"order_id": order_id, **order} if order else {"error": "Order not found"}
        if name == "request_refund":
            order_id = arguments.get("order_id", "")
            if order_id not in ORDERS:
                return {"error": "Order not found"}
            request = {"order_id": order_id, "reason": arguments.get("reason", "unspecified")}
            self.refund_requests.append(request)
            return {"status": "refund request recorded", **request}
        if name == "create_support_ticket":
            ticket = {
                "subject": arguments.get("subject", "Support request"),
                "customer_id": arguments.get("customer_id", ""),
            }
            self.tickets.append(ticket)
            return {"status": "ticket created", "ticket_number": f"T-{len(self.tickets):04d}", **ticket}
        return {"error": f"Unknown tool: {name}"}


class SupportAssistant:
    """A deliberately small rule-based assistant used to exercise eval workflows."""

    prompt_version = "crm-v2"

    def __init__(self, crm: CRM | None = None) -> None:
        self.crm = crm or CRM()

    def run(self, user_input: str) -> tuple[str, list[ToolCall]]:
        text = user_input.strip()
        lowered = text.lower()
        calls: list[ToolCall] = []

        def invoke(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            result = self.crm.call(name, arguments)
            calls.append(ToolCall(name, arguments, result))
            return result

        if "refund" in lowered or "money back" in lowered:
            order_id = _find_id(text, "O-")
            if not order_id:
                return "Please share your order number so I can check the refund options.", calls
            order = invoke("get_order", {"order_id": order_id})
            if "error" in order:
                return "I couldn't find that order. Please check the order number.", calls
            reason = " ".join(text.split()[-5:]) or "customer request"
            result = invoke("request_refund", {"order_id": order_id, "reason": reason})
            return f"I've recorded a refund request for order {order_id}. {result['status'].capitalize()}.", calls

        if "order" in lowered or "delivery" in lowered or "shipped" in lowered:
            order_id = _find_id(text, "O-")
            if not order_id:
                return "Please share your order number and I'll check its status.", calls
            result = invoke("get_order", {"order_id": order_id})
            if "error" in result:
                return "I couldn't find that order. Please check the order number.", calls
            return f"Order {order_id} ({result['item']}) is {result['status']}.", calls

        if any(word in lowered for word in ("issue", "problem", "broken", "help")):
            customer_id = _find_id(text, "C-") or ""
            result = invoke(
                "create_support_ticket",
                {"subject": text[:80] or "Support request", "customer_id": customer_id},
            )
            return f"I created support ticket {result['ticket_number']} for you.", calls

        if "customer" in lowered or "account" in lowered or "email" in lowered:
            customer_id = _find_id(text, "C-")
            if not customer_id:
                return "Please share your customer ID so I can look up the account.", calls
            result = invoke("lookup_customer", {"customer_id": customer_id})
            if "error" in result:
                return "I couldn't find that customer ID.", calls
            return f"The account is for {result['name']} ({result['email']}).", calls

        return "I can help with account lookups, order status, refund requests, or support tickets.", calls


def _find_id(text: str, prefix: str) -> str | None:
    match = re.search(rf"\b{re.escape(prefix)}\d+\b", text)
    return match.group(0) if match else None
