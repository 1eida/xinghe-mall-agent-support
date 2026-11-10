"""Business tools used by the Qwen customer-support agent."""

from __future__ import annotations

import hashlib

from langchain_core.tools import tool

from customer_support.policy import search_policy
from customer_support.store import (
    create_support_ticket,
    get_order_status,
    refund_eligibility,
)


@tool("search_policy")
def search_policy_tool(query: str) -> dict:
    """Search the ecommerce refund, shipping, warranty, and invoice policies."""
    return search_policy(query)


@tool("get_order_status")
def get_order_status_tool(order_id: str, phone_last4: str) -> dict:
    """Get a demo order such as ORD1001 after phone-last-four verification."""
    return get_order_status(order_id, phone_last4)


@tool("check_refund_eligibility")
def check_refund_eligibility_tool(order_id: str, phone_last4: str) -> dict:
    """Check a demo order against the demo seven-day refund policy."""
    return refund_eligibility(order_id, phone_last4)


@tool("create_support_ticket")
def create_support_ticket_tool(
    order_id: str,
    phone_last4: str,
    category: str,
    summary: str,
) -> dict:
    """Create a support ticket after identity verification and human approval."""
    order = get_order_status(order_id, phone_last4)
    if not order["ok"]:
        return order
    fingerprint = hashlib.sha256(
        f"{order_id.upper()}:{category.strip()}:{summary.strip()}".encode()
    ).hexdigest()[:16]
    return create_support_ticket(
        order_id=order_id,
        category=category,
        summary=summary,
        idempotency_key=f"agent-{fingerprint}",
    )


CUSTOMER_SUPPORT_TOOLS = [
    search_policy_tool,
    get_order_status_tool,
    check_refund_eligibility_tool,
    create_support_ticket_tool,
]
