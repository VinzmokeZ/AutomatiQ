import json
import logging

import litellm

from . import config

logger = logging.getLogger(__name__)


def extract_message(exc) -> str:
    """Pull a readable summary from an exception, stripping litellm wrapper noise."""
    import re

    def _clean(raw):
        s = str(raw)
        s = re.sub(r"^(?:[\w\.]+:\s*)+", "", s)
        s = re.sub(r"^\w+Exception\s+\w+\s*-\s*", "", s)
        json_match = re.search(r"\{.*\}", s, re.DOTALL)
        if json_match:
            try:
                body = json.loads(json_match.group())
                if "error" in body:
                    err = body["error"]
                    if isinstance(err, dict) and "message" in err:
                        return err["message"]
                    return str(err)
                if "message" in body:
                    return body["message"]
            except json.JSONDecodeError:
                pass
        return s.split("\n")[0][:300]

    return _clean(exc)


def _build_model_help(model: str, original_msg: str) -> str:
    """Build a simple error message for an invalid or unsupported model."""
    if "/" not in model:
        return (
            f"Invalid model string '{model}'. Expected format: 'provider/model-name' "
            f"(e.g. 'gemini/gemini-2.5-flash').\n"
            f"Original error: {original_msg}"
        )

    return (
        f"The requested model '{model}' either does not exist, is not supported by the provider, "
        f"or there is a problem on their server side.\n"
        f"Original error: {original_msg}"
    )


def _is_model_error(exc: Exception) -> bool:
    msg = extract_message(exc).lower()
    needles = [
        "llm provider not provided",
        "unable to map your input to a model",
        "invalid model",
        "model not found",
        "unknown model",
        "unsupported model",
        "model is not supported",
    ]
    return any(n in msg for n in needles)


def call_llm_blocking(msgs: list[dict], tools: list[dict]):
    """Blocking LLM call to litellm."""
    kwargs = dict(
        model=config.AGENT_MODEL,
        messages=msgs,
        tools=tools,
        tool_choice="auto",
        temperature=0.3,
    )
    if config.API_BASE:
        kwargs["api_base"] = config.API_BASE

    # Enable extended thinking/reasoning for models that support it
    if litellm.supports_reasoning(model=config.AGENT_MODEL):
        kwargs["reasoning_effort"] = "high"

    try:
        return litellm.completion(**kwargs)
    except Exception as exc:
        if _is_model_error(exc):
            msg = extract_message(exc)
            raise ValueError(_build_model_help(config.AGENT_MODEL, msg)) from exc
        raise
