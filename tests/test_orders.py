import json

from src.agent.orders import normalize_order_id, order_lookup

FORBIDDEN = (
    '"customer"',
    '"internal"',
    "risk_score",
    "warehouse_note",
    "support_tags",
    "example.test",
    "shipping_address",
)


def payload(order_id):
    return json.dumps(order_lookup(order_id))


def test_ids_are_normalised():
    assert normalize_order_id("  ord-1007 ")[0] == "ORD-1007"
    assert normalize_order_id("ORD 1007")[0] == "ORD-1007"
    assert normalize_order_id("1007")[0] == "ORD-1007"
    assert normalize_order_id("ORD-1007.")[0] == "ORD-1007"


def test_unusable_ids_are_reported_not_guessed():
    assert normalize_order_id("banana") == (None, "malformed")
    assert normalize_order_id("") == (None, "missing")
    assert order_lookup("banana")["found"] is False
    assert order_lookup("ORD-9999")["reason"] == "not_found"
    assert "status" not in order_lookup("ORD-9999")


def test_result_never_contains_internal_or_customer_fields():
    for order_id in ["ORD-100{0}".format(index) for index in range(1, 10)]:
        text = payload(order_id)
        for field in FORBIDDEN:
            assert field not in text


def test_cancelled_order_hides_stale_delivery_fields():
    result = order_lookup("ORD-1004")
    assert result["status"] == "cancelled"
    assert result["carrier"] is None
    assert result["tracking_number"] is None
    assert result["estimated_delivery"] is None
    assert result["delivery_expectation"] == "none"
    assert set(result["suppressed_fields"]) == {"carrier", "tracking_number", "estimated_delivery"}


def test_returned_order_hides_stale_delivery_fields():
    result = order_lookup("ORD-1008")
    assert result["estimated_delivery"] is None
    assert result["delivery_expectation"] == "none"


def test_shipped_order_without_estimate_is_marked_unavailable():
    result = order_lookup("ORD-1011")
    assert result["status"] == "shipped"
    assert result["carrier"] == "Canada Post"
    assert result["estimate_available"] is False
    assert result["estimated_delivery_display"] is None


def test_shipped_order_with_estimate_exposes_a_display_date():
    result = order_lookup("ORD-1007")
    assert result["estimated_delivery_display"] == "August 22, 2026"
    assert result["estimate_available"] is True


def test_exception_status_requires_human_review():
    result = order_lookup("ORD-1010")
    assert result["requires_human"] is True


def test_cancellation_window_uses_the_dataset_snapshot():
    assert order_lookup("ORD-1001")["cancellation_window_open"] is True
    assert order_lookup("ORD-1002")["cancellation_window_open"] is False
    assert order_lookup("ORD-1012")["cancellation_window_open"] is False
