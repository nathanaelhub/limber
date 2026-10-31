"""
The one place Limber calls the Claude API (feature 018, FR-001).

`assistant` builds a request body (a plain dict of `messages.create` arguments) and hands it to a client.
`AnthropicClient` sends it with the official SDK; `FakeClient` records it and answers from a script, so no
test ever makes a network call. `make_client()` is looked up at call time, so tests can replace it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Protocol, Union

from src.assist import config


class AssistUnavailable(Exception):
    """The API could not be reached, refused the key, or failed. The screen says the assistant isn't
    available right now; the reason word goes to the host log, never the request or response text."""

    def __init__(self, reason: str = "error"):
        super().__init__(reason)
        self.reason = reason


@dataclass
class Reply:
    text: str                        # the final text block; "" when there was none
    stop_reason: Optional[str]
    model: str                       # the model that answered (a fallback can differ from the one asked)
    input_tokens: int = 0            # including cache reads and writes
    output_tokens: int = 0


class Client(Protocol):
    def send(self, body: dict) -> Reply: ...


class AnthropicClient:
    """Sends through `client.beta.messages.create`, because server-side fallbacks are a beta parameter."""

    TIMEOUT_SECONDS = 90.0

    def __init__(self, api_key: str):
        import anthropic
        self._anthropic = anthropic
        self._sdk = anthropic.Anthropic(api_key=api_key, timeout=self.TIMEOUT_SECONDS, max_retries=2)

    def send(self, body: dict) -> Reply:
        a = self._anthropic
        try:
            response = self._sdk.beta.messages.create(**body)
        except a.AuthenticationError:
            raise AssistUnavailable("auth")
        except a.PermissionDeniedError:
            raise AssistUnavailable("permission")
        except a.RateLimitError:
            raise AssistUnavailable("rate_limited")
        except a.BadRequestError:
            raise AssistUnavailable("bad_request")
        except a.APIStatusError as err:
            raise AssistUnavailable("overloaded" if err.status_code in (500, 502, 503, 529) else f"http_{err.status_code}")
        except a.APITimeoutError:
            raise AssistUnavailable("timeout")
        except a.APIConnectionError:
            raise AssistUnavailable("network")
        text = ""
        for block in response.content:
            if block.type == "text":
                text = block.text
        usage = response.usage
        tokens_in = (usage.input_tokens or 0) + (getattr(usage, "cache_read_input_tokens", 0) or 0) + \
            (getattr(usage, "cache_creation_input_tokens", 0) or 0)
        return Reply(text=text, stop_reason=response.stop_reason, model=response.model,
                     input_tokens=tokens_in, output_tokens=usage.output_tokens or 0)


class FakeClient:
    """Answers from a script of replies (or exceptions to raise) and keeps every request body it was sent."""

    def __init__(self, script: List[Union[Reply, Exception]]):
        self.script = list(script)
        self.bodies: List[dict] = []

    def send(self, body: dict) -> Reply:
        self.bodies.append(body)
        if not self.script:
            raise AssertionError("FakeClient was called more times than scripted")
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def make_client() -> Client:
    key = config.api_key()
    if key is None:
        raise AssistUnavailable("no_key")
    return AnthropicClient(key)
