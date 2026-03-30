"""OpenAI Responses API gray adapter for selected long-text stages."""

from __future__ import annotations

import os
from time import time
from typing import Any, Optional
from urllib.parse import urlparse

from langchain_core.messages import AIMessage
from openai import OpenAI

from tradingagents.config.runtime_settings import get_bool
from tradingagents.llm_adapters.http_client_utils import build_openai_sdk_client_kwargs
from tradingagents.utils.logging_init import get_logger

logger = get_logger("default")

_RESPONSES_STAGE_WHITELIST = {"Research Manager"}


def _coerce_secret(value: Any) -> Optional[str]:
    if value is None:
        return None
    try:
        if hasattr(value, "get_secret_value"):
            return value.get_secret_value()
    except Exception:
        pass
    if isinstance(value, str):
        return value
    return str(value)


def _resolve_model_name(llm: Any) -> Optional[str]:
    return (
        getattr(llm, "model_name", None)
        or getattr(llm, "model", None)
        or getattr(llm, "_model_name_alias", None)
    )


def _resolve_base_url(llm: Any) -> Optional[str]:
    base_url = getattr(llm, "openai_api_base", None) or getattr(llm, "base_url", None)
    if base_url:
        return str(base_url)

    root_client = getattr(llm, "root_client", None)
    if root_client is not None:
        root_base_url = getattr(root_client, "base_url", None)
        if root_base_url:
            return str(root_base_url)

    client = getattr(llm, "client", None)
    if client is not None:
        client_base_url = getattr(client, "base_url", None)
        if client_base_url:
            return str(client_base_url)

    return None


def _resolve_api_key(llm: Any) -> Optional[str]:
    return (
        _coerce_secret(getattr(llm, "openai_api_key", None))
        or _coerce_secret(getattr(llm, "api_key", None))
        or os.getenv("OPENAI_API_KEY")
    )


def _resolve_timeout(llm: Any) -> Optional[float]:
    timeout = getattr(llm, "request_timeout", None) or getattr(llm, "timeout", None)
    try:
        return float(timeout) if timeout is not None else None
    except Exception:
        return None


def _looks_like_official_openai(base_url: Optional[str]) -> bool:
    if not base_url:
        return False
    try:
        hostname = (urlparse(base_url).hostname or "").lower()
    except Exception:
        hostname = ""
    return hostname in {"api.openai.com"} or hostname.endswith(".openai.com")


def _allow_compatible_gateways() -> bool:
    return get_bool(
        "TA_OPENAI_RESPONSES_ALLOW_COMPAT",
        "ta_openai_responses_allow_compat",
        False,
    )


def supports_openai_responses(llm: Any, stage_name: str, prompt: Any) -> bool:
    """Return whether this request should use the Responses API gray path."""
    if stage_name not in _RESPONSES_STAGE_WHITELIST:
        return False

    if not isinstance(prompt, str) or not prompt.strip():
        return False

    if not get_bool(
        "TA_OPENAI_RESPONSES_ENABLED",
        "ta_openai_responses_enabled",
        True,
    ):
        return False

    model_name = _resolve_model_name(llm)
    base_url = _resolve_base_url(llm)
    api_key = _resolve_api_key(llm)

    if not model_name or not base_url or not api_key:
        return False

    if _looks_like_official_openai(base_url):
        return True

    return _allow_compatible_gateways()


def _extract_response_text(response: Any) -> str:
    output_text = getattr(response, "output_text", None)
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()

    output = getattr(response, "output", None)
    if isinstance(output, list):
        parts: list[str] = []
        for item in output:
            content_list = getattr(item, "content", None) or (
                item.get("content") if isinstance(item, dict) else None
            )
            if not isinstance(content_list, list):
                continue
            for content in content_list:
                text = getattr(content, "text", None) or (
                    content.get("text") if isinstance(content, dict) else None
                )
                if isinstance(text, str):
                    parts.append(text)
        if parts:
            return "".join(parts).strip()

    return ""


def invoke_responses_text(llm: Any, prompt: str, stage_name: str) -> AIMessage:
    """Invoke OpenAI Responses API and rebuild the result into an AIMessage."""
    model_name = _resolve_model_name(llm)
    base_url = _resolve_base_url(llm)
    api_key = _resolve_api_key(llm)
    temperature = getattr(llm, "temperature", None)
    max_tokens = getattr(llm, "max_tokens", None)
    timeout = _resolve_timeout(llm)

    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        **build_openai_sdk_client_kwargs(),
    )
    request_kwargs = {
        "model": model_name,
        "input": prompt,
        "text": {"format": {"type": "text"}},
    }
    if temperature is not None:
        request_kwargs["temperature"] = temperature
    if max_tokens is not None:
        request_kwargs["max_output_tokens"] = max_tokens
    if timeout is not None:
        request_kwargs["timeout"] = timeout

    start_time = time()
    try:
        with client.responses.stream(**request_kwargs) as stream:
            collected_parts: list[str] = []
            event_count = 0

            for event in stream:
                event_count += 1
                if getattr(event, "type", "") == "response.output_text.delta":
                    delta = getattr(event, "delta", "")
                    if isinstance(delta, str) and delta:
                        collected_parts.append(delta)

            final_response = stream.get_final_response()
            final_text = _extract_response_text(final_response) or "".join(collected_parts).strip()

        elapsed = time() - start_time
        if not final_text:
            raise ValueError("Responses API 返回空文本")

        logger.info(
            f"🧩 [{stage_name}] 使用 OpenAI Responses API 成功: model={model_name}, "
            f"长度={len(final_text)} 字符, 事件数={event_count}, 耗时={elapsed:.2f}秒"
        )
        return AIMessage(content=final_text)
    except Exception as exc:
        elapsed = time() - start_time
        logger.warning(
            f"⚠️ [{stage_name}] OpenAI Responses API 失败，回退到 LangChain 默认路径: {exc} "
            f"(base_url={base_url}, model={model_name}, 耗时={elapsed:.2f}秒)"
        )
        raise
