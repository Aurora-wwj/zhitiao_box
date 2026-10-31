"""NiceCode integration seam with an explicitly selected wire protocol."""

import json
import math
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .config import NiceCodeConfig
from .errors import AgentError, ErrorCode
from .models import OperationResult, invoke

MAX_RESPONSE_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes


class Transport(Protocol):
    def send(
        self, url: str, headers: dict[str, str], body: bytes, timeout_s: float,
    ) -> HttpResponse: ...


class WireAdapter(Protocol):
    path: str

    def payload(self, model: str, messages: list[dict[str, str]]) -> dict[str, Any]: ...

    def parse(self, document: Any) -> str: ...


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class UrllibTransport:
    """Uses system TLS verification; refuses redirects and oversized responses."""

    def send(
        self, url: str, headers: dict[str, str], body: bytes, timeout_s: float,
    ) -> HttpResponse:
        request = Request(url, data=body, headers=headers, method="POST")
        try:
            with build_opener(_NoRedirect()).open(request, timeout=timeout_s) as response:
                content = response.read(MAX_RESPONSE_BYTES + 1)
                if len(content) > MAX_RESPONSE_BYTES:
                    raise AgentError(ErrorCode.INVALID_RESPONSE, "Response is too large.")
                return HttpResponse(response.status, content)
        except HTTPError as exc:
            status = exc.code
            exc.close()
            return HttpResponse(status, b"")
        except URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise TimeoutError() from None
            raise AgentError(
                ErrorCode.NETWORK_UNREACHABLE, "Cannot reach the API service."
            ) from None


class OpenAIChatAdapter:
    """Opt-in example. NiceCode compatibility requires provider documentation."""

    path = "chat/completions"

    def payload(self, model: str, messages: list[dict[str, str]]) -> dict[str, Any]:
        return {"model": model, "messages": messages, "stream": False}

    def parse(self, document: Any) -> str:
        if isinstance(document, dict) and document.get("error"):
            raise AgentError(ErrorCode.SERVICE_ERROR, "API returned a service error.")
        try:
            content = document["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise AgentError(ErrorCode.INVALID_RESPONSE, "Missing assistant content.") from None
        if not isinstance(content, str) or not content.strip():
            raise AgentError(ErrorCode.INVALID_RESPONSE, "Invalid assistant content.")
        return content


class OpenAIResponsesAdapter:
    """Responses wire protocol selected by NiceCode's public Codex setup script."""

    path = "responses"

    def payload(self, model: str, messages: list[dict[str, str]]) -> dict[str, Any]:
        return {"model": model, "input": messages, "stream": False, "store": False}

    def parse(self, document: Any) -> str:
        if not isinstance(document, dict):
            raise AgentError(ErrorCode.INVALID_RESPONSE, "Invalid Responses document.")
        if document.get("error") or document.get("status") == "failed":
            raise AgentError(ErrorCode.SERVICE_ERROR, "API returned a service error.")
        if document.get("status") != "completed":
            raise AgentError(ErrorCode.INVALID_RESPONSE, "API response did not complete.")
        output = document.get("output")
        if not isinstance(output, list):
            raise AgentError(ErrorCode.INVALID_RESPONSE, "Missing Responses output.")
        texts: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                raise AgentError(ErrorCode.INVALID_RESPONSE, "Invalid output item.")
            if item.get("type") == "reasoning":
                continue
            if item.get("type") != "message" or item.get("role") != "assistant":
                raise AgentError(
                    ErrorCode.INVALID_RESPONSE,
                    "Only assistant text is supported; model tool calls are not executed.",
                )
            if item.get("status") != "completed":
                raise AgentError(ErrorCode.INVALID_RESPONSE, "Assistant message did not complete.")
            content = item.get("content")
            if not isinstance(content, list):
                raise AgentError(ErrorCode.INVALID_RESPONSE, "Invalid assistant content.")
            for part in content:
                if not isinstance(part, dict):
                    raise AgentError(ErrorCode.INVALID_RESPONSE, "Invalid content part.")
                if part.get("type") == "refusal":
                    raise AgentError(ErrorCode.SERVICE_ERROR, "Model declined the request.")
                text = part.get("text")
                if part.get("type") != "output_text" or not isinstance(text, str):
                    raise AgentError(ErrorCode.INVALID_RESPONSE, "Invalid text content.")
                if text.strip():
                    texts.append(text)
        if not texts:
            raise AgentError(ErrorCode.INVALID_RESPONSE, "Missing assistant text.")
        return "\n".join(texts)


class NiceCodeClient:
    def __init__(
        self, config: NiceCodeConfig, *, adapter: WireAdapter | None = None,
        transport: Transport | None = None,
    ) -> None:
        self.config = config
        self.adapter = adapter
        self.transport = transport if transport is not None else UrllibTransport()

    def generate(self, messages: list[dict[str, str]], *, timeout_s: float | None = None) -> OperationResult:
        def operation() -> dict[str, Any]:
            timeout = self.config.timeout_s
            if timeout_s is not None:
                try:
                    valid = type(timeout_s) in (int, float) and math.isfinite(timeout_s) and timeout_s > 0
                except OverflowError:
                    valid = False
                if not valid:
                    raise AgentError(ErrorCode.INVALID_ARGUMENT, "Require a finite positive request budget.")
                timeout = min(timeout, timeout_s)
            if self.adapter is None:
                raise AgentError(
                    ErrorCode.CONFIGURATION_ERROR,
                    "Select an API adapter after confirming the provider protocol.",
                )
            if not isinstance(messages, list) or not messages:
                raise AgentError(ErrorCode.INVALID_ARGUMENT, "Require chat messages.")
            for message in messages:
                if (
                    not isinstance(message, dict)
                    or set(message) != {"role", "content"}
                    or message.get("role") not in ("system", "user", "assistant")
                    or not isinstance(message.get("content"), str)
                    or not message["content"].strip()
                ):
                    raise AgentError(ErrorCode.INVALID_ARGUMENT, "Invalid chat message.")
            path = self.adapter.path
            if (
                not isinstance(path, str) or not path
                or any(part in path for part in (":", "?", "#", "\\"))
                or path.startswith("/") or ".." in path.split("/")
            ):
                raise AgentError(ErrorCode.CONFIGURATION_ERROR, "Invalid API adapter path.")
            body = json.dumps(
                self.adapter.payload(self.config.model, messages), allow_nan=False,
            ).encode("utf-8")
            response = self.transport.send(
                self.config.base_url.rstrip("/") + "/" + path,
                {"Authorization": "Bearer " + self.config.api_key,
                 "Content-Type": "application/json", "Accept": "application/json"},
                body, timeout,
            )
            if not 200 <= response.status < 300:
                raise AgentError(
                    ErrorCode.SERVICE_ERROR,
                    f"API returned HTTP {response.status}.",
                    status_code=response.status,
                )
            if len(response.body) > MAX_RESPONSE_BYTES:
                raise AgentError(ErrorCode.INVALID_RESPONSE, "Response is too large.")
            try:
                document = json.loads(response.body)
            except (ValueError, UnicodeError):
                raise AgentError(ErrorCode.INVALID_RESPONSE, "API returned invalid JSON.") from None
            content = self.adapter.parse(document)
            try:
                content.encode("utf-8")
            except (AttributeError, UnicodeError):
                raise AgentError(ErrorCode.INVALID_RESPONSE, "API text must be valid Unicode.") from None
            return {"content": content}

        return invoke(operation, backend="nicecode")
