import re
import time

from .config import settings

RETRY_DELAY = re.compile(r"retry(?:Delay|\s+in)['\":\s]+(\d+(?:\.\d+)?)s", re.IGNORECASE)
RETRYABLE = re.compile(
    r"\b(429|500|502|503|504)\b|rate.?limit|resource_exhausted|quota|unavailable|overloaded"
    r"|high demand|timed? ?out",
    re.IGNORECASE,
)

MAX_ATTEMPTS = 6
MAX_BACKOFF = 65.0


class LLMError(RuntimeError):
    pass


def retry_after(message, attempt):
    match = RETRY_DELAY.search(message)
    if match:
        return min(float(match.group(1)) + 1.0, MAX_BACKOFF)
    return min(4.0 * (2 ** attempt), MAX_BACKOFF)


class LLMClient:
    def __init__(self, settings_override=None):
        self.settings = settings_override or settings
        self._client = None
        self._last_request = 0.0

    @property
    def client(self):
        if self._client is None:
            if not self.settings.api_key:
                raise LLMError(
                    "LLM_API_KEY is not set. Copy .env.example to .env and add a key, "
                    "or run the evaluation with --no-llm."
                )
            from openai import OpenAI

            self._client = OpenAI(
                api_key=self.settings.api_key,
                base_url=self.settings.base_url or None,
            )
        return self._client

    def _pace(self):
        interval = self.settings.min_interval
        if interval <= 0:
            return
        elapsed = time.time() - self._last_request
        if elapsed < interval:
            time.sleep(interval - elapsed)

    def complete(self, messages, tools=None):
        last_error = ""
        for attempt in range(MAX_ATTEMPTS):
            self._pace()
            self._last_request = time.time()
            try:
                response = self.client.chat.completions.create(
                    model=self.settings.model,
                    messages=messages,
                    tools=tools or None,
                    temperature=self.settings.temperature,
                )
            except LLMError:
                raise
            except Exception as error:
                last_error = str(error)
                if not RETRYABLE.search(last_error) or attempt == MAX_ATTEMPTS - 1:
                    raise LLMError(last_error) from error
                time.sleep(retry_after(last_error, attempt))
                continue
            return response.choices[0].message
        raise LLMError(last_error)


class StubClient:
    def __init__(self, responder=None):
        self.responder = responder
        self.calls = []

    def complete(self, messages, tools=None):
        self.calls.append(messages)
        if self.responder:
            return self.responder(messages, tools)
        raise LLMError("no stub responder configured")
