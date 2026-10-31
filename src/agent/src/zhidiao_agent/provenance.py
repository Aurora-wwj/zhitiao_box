"""Allowlisted request-model metadata, never authentication or raw config."""

from .errors import AgentError, ErrorCode
from .nicecode import NiceCodeClient, OpenAIChatAdapter, OpenAIResponsesAdapter


def validate_model_info(info: dict) -> dict:
    if (not isinstance(info, dict) or set(info) != {"source", "requested_model", "protocol"}
            or any(not isinstance(value, str) or not value.strip() or len(value) > 256 for value in info.values())
            or info["source"] not in {"nicecode_api", "scripted", "custom", "uninitialized"}):
        raise AgentError(ErrorCode.INVALID_ARGUMENT, "Invalid model provenance fields.")
    return dict(info)


def describe_model(client=None, *, hint: dict | None = None) -> dict:
    """Describe the requested route/model; this does not attest provider weights.

    Only native clients have their settings inspected. Arbitrary callbacks and
    mocks must not have their repr, credentials, or dynamic attributes exported.
    A trusted launcher can supply a non-secret hint before client construction.
    """
    if isinstance(client, NiceCodeClient):
        protocol = ("openai-responses" if isinstance(client.adapter, OpenAIResponsesAdapter)
                    else "openai-chat" if isinstance(client.adapter, OpenAIChatAdapter) else "custom")
        return validate_model_info({"source": "nicecode_api", "requested_model": client.config.model,
                                    "protocol": protocol})
    if hint is not None:
        return validate_model_info(hint)
    return {"source": "uninitialized" if client is None else "custom",
            "requested_model": "unreported", "protocol": "unreported" if client is None else "custom"}
