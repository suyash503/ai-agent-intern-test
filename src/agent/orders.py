import json
import re
from datetime import datetime, timezone
from functools import lru_cache

from .config import settings
from .retriever import scrub

ORDER_ID = re.compile(r"^(?:ORD)?[\s\-_]?(\d{3,6})$")
ORDER_MENTION = re.compile(r"\bORD[\s\-_]?(\d{3,6})\b", re.IGNORECASE)

MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

CANCELLATION_WINDOW_MINUTES = 30

TERMINAL_STATUSES = {"cancelled", "returned"}


@lru_cache(maxsize=1)
def load_dataset(path=None):
    target = path or settings.orders_path
    with open(target, encoding="utf-8") as handle:
        return json.load(handle)


def snapshot_time(dataset=None):
    dataset = dataset or load_dataset()
    return _parse(dataset["snapshot_at"])


def _parse(value):
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def _display_date(value):
    if not value:
        return None
    parsed = _parse(value if "T" in value else value + "T00:00:00Z")
    return "{0} {1}, {2}".format(MONTHS[parsed.month - 1], parsed.day, parsed.year)


def normalize_order_id(raw):
    if raw is None:
        return None, "missing"
    text = str(raw).strip().strip(".,;:!?\"'()[]")
    if not text:
        return None, "missing"
    mention = ORDER_MENTION.search(text)
    if mention:
        return "ORD-{0}".format(mention.group(1)), "normalized"
    match = ORDER_ID.match(text.upper())
    if not match:
        return None, "malformed"
    return "ORD-{0}".format(match.group(1)), "normalized"


def extract_order_id(text):
    if not text:
        return None
    mention = ORDER_MENTION.search(text)
    if mention:
        return "ORD-{0}".format(mention.group(1))
    return None


def _items(order):
    return [
        {
            "name": item.get("name"),
            "quantity": item.get("quantity"),
            "final_sale": item.get("final_sale"),
        }
        for item in order.get("items", [])
    ]


def _find(dataset, order_id):
    for order in dataset.get("orders", []):
        if order.get("order_id", "").upper() == order_id:
            return order
    return None


def order_lookup(order_id, dataset=None):
    dataset = dataset or load_dataset()
    normalized, reason = normalize_order_id(order_id)
    if normalized is None:
        return {
            "found": False,
            "reason": reason,
            "requested": (str(order_id).strip() if order_id else None),
            "guidance": (
                "No order ID was supplied. Ask the customer for the order ID."
                if reason == "missing"
                else "The supplied value is not a valid order ID. Ask the customer to confirm it."
            ),
        }

    order = _find(dataset, normalized)
    if order is None:
        return {
            "found": False,
            "reason": "not_found",
            "requested": normalized,
            "guidance": (
                "No order matches this ID in the order system. Do not guess a different order. "
                "Ask the customer to re-check the ID and recommend human support."
            ),
        }

    status = str(order.get("status", "unknown")).lower()
    placed_at = _parse(order.get("placed_at"))
    now = snapshot_time(dataset)
    minutes_since_placed = None
    if placed_at and now:
        minutes_since_placed = (now - placed_at).total_seconds() / 60

    result = {
        "found": True,
        "order_id": order.get("order_id"),
        "status": status,
        "membership_tier": order.get("membership_tier"),
        "items": _items(order),
        "placed_at": order.get("placed_at"),
        "status_updated_at": order.get("status_updated_at"),
        "shipped_at": order.get("shipped_at"),
        "delivered_at": order.get("delivered_at"),
        "carrier": order.get("carrier"),
        "tracking_number": order.get("tracking_number"),
        "estimated_delivery": order.get("estimated_delivery"),
        "customer_safe_message": order.get("customer_safe_message"),
        "suppressed_fields": [],
        "notes": [],
    }

    if status in TERMINAL_STATUSES:
        for field in ("carrier", "tracking_number", "estimated_delivery"):
            if result[field] is not None:
                result["suppressed_fields"].append(field)
            result[field] = None
        result["delivery_expectation"] = "none"
        result["estimate_available"] = False
        result["notes"].append(
            "Status is {0}. Carrier, tracking, and delivery-estimate fields were dropped because "
            "they are stale operational data. {1}".format(
                status,
                "This order will not be shipped."
                if status == "cancelled"
                else "This order was returned and no further delivery is expected.",
            )
        )
    elif status == "delivered":
        result["delivery_expectation"] = "delivered"
        result["estimate_available"] = False
    elif status == "exception":
        result["delivery_expectation"] = "unknown"
        result["estimate_available"] = bool(result["estimated_delivery"])
        result["notes"].append(
            "Status is exception. A human support specialist must review this shipment."
        )
    elif result["estimated_delivery"]:
        result["delivery_expectation"] = "estimated"
        result["estimate_available"] = True
    else:
        result["delivery_expectation"] = "unknown"
        result["estimate_available"] = False
        result["notes"].append(
            "No delivery estimate is available for this order. Do not calculate or invent one."
        )

    result["estimated_delivery_display"] = _display_date(result["estimated_delivery"])
    result["delivered_at_display"] = _display_date(result["delivered_at"])
    result["shipped_at_display"] = _display_date(result["shipped_at"])
    result["requires_human"] = status == "exception"
    result["cancellation_window_open"] = bool(
        status == "pending"
        and minutes_since_placed is not None
        and minutes_since_placed <= CANCELLATION_WINDOW_MINUTES
    )
    result["minutes_since_placed"] = (
        round(minutes_since_placed) if minutes_since_placed is not None else None
    )
    if not result["cancellation_window_open"]:
        result["notes"].append(
            "The 30-minute cancellation window is not open for this order. Explain the policy and "
            "recommend human support instead of promising a cancellation."
        )
    if result["customer_safe_message"]:
        cleaned, flagged = scrub(result["customer_safe_message"])
        result["customer_safe_message"] = cleaned
        if flagged:
            result["notes"].append("Instruction-like text in the order record was removed.")
    return result


def tool_schema():
    return {
        "type": "function",
        "function": {
            "name": "order_lookup",
            "description": (
                "Look up the current status of a single Aster & Row order. Call this whenever the "
                "customer asks about an order, shipment, tracking, cancellation eligibility, or "
                "delivery date. Never answer an order question without calling it."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {
                        "type": "string",
                        "description": "The order ID supplied by the customer, for example ORD-1007.",
                    }
                },
                "required": ["order_id"],
            },
        },
    }
