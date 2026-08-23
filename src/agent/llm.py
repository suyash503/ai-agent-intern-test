from .config import settings


class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(self, settings_override=None):
        self.settings = settings_override or settings
        self._client = None

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

    def complete(self, messages, tools=None):
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
            raise LLMError(str(error)) from error
        return response.choices[0].message


class StubClient:
    def __init__(self, responder=None):
        self.responder = responder
        self.calls = []

    def complete(self, messages, tools=None):
        self.calls.append(messages)
        if self.responder:
            return self.responder(messages, tools)
        raise LLMError("no stub responder configured")
