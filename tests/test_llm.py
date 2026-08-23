import pytest

from src.agent.llm import LLMClient, LLMError, retry_after

PER_MINUTE = (
    "Error code: 429 - quotaId: 'GenerateRequestsPerMinutePerProjectPerModel-FreeTier', "
    "retryDelay: '26s'"
)
PER_DAY = (
    "Error code: 429 - quotaId: 'GenerateRequestsPerDayPerProjectPerModel-FreeTier', "
    "retryDelay: '55s'"
)


class Boom:
    def __init__(self, message, limit=99):
        self.message = message
        self.calls = 0
        self.limit = limit

    def create(self, **kwargs):
        self.calls += 1
        if self.calls > self.limit:
            raise AssertionError("retried after a fatal error")
        raise RuntimeError(self.message)


class FakeClient:
    def __init__(self, boom):
        self.chat = type("chat", (), {"completions": boom})()


def client_with(boom, monkeypatch):
    client = LLMClient()
    monkeypatch.setattr(LLMClient, "client", property(lambda self: FakeClient(boom)))
    monkeypatch.setattr("src.agent.llm.time.sleep", lambda seconds: None)
    return client


def test_server_retry_delay_is_honoured():
    assert retry_after(PER_MINUTE, 0) == pytest.approx(27.0)


def test_backoff_grows_without_a_server_hint():
    assert retry_after("Error code: 503 overloaded", 0) < retry_after("Error code: 503 overloaded", 3)


def test_per_minute_quota_is_retried(monkeypatch):
    boom = Boom(PER_MINUTE)
    client = client_with(boom, monkeypatch)
    with pytest.raises(LLMError):
        client.complete([{"role": "user", "content": "hi"}])
    assert boom.calls > 1


def test_daily_quota_fails_immediately(monkeypatch):
    boom = Boom(PER_DAY, limit=1)
    client = client_with(boom, monkeypatch)
    with pytest.raises(LLMError) as error:
        client.complete([{"role": "user", "content": "hi"}])
    assert "daily" in str(error.value)
    assert boom.calls == 1


def test_a_non_retryable_error_is_not_retried(monkeypatch):
    boom = Boom("Error code: 400 - malformed request", limit=1)
    client = client_with(boom, monkeypatch)
    with pytest.raises(LLMError):
        client.complete([{"role": "user", "content": "hi"}])
    assert boom.calls == 1
