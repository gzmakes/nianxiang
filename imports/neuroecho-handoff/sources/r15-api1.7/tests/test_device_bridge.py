"""The simulator remains a unit-test helper, never a production endpoint."""
from server import device_bridge


def test_button_fixture_returns_correlated_ack():
    event = device_bridge.button_press("unit-only")
    assert event["type"] == "button.press" and event["source"] == "synthetic-button"
    assert event["ack"]["status"] == "received"
    assert event["ack"]["for"] == event["id"]


def test_display_fixture_has_explicit_synthetic_state():
    result = device_bridge.display("unit-only", "测试资料", "amber")
    assert result["ack"]["status"] == "displayed"
    assert result["ack"]["latency_ms"] > 0
    state = device_bridge.state()
    assert state["last_display"]["id"] == result["id"]
    assert state["synthetic"] is True
