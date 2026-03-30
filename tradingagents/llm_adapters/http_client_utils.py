"""Helpers for optional OpenAI/httpx SSL client customization."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

import httpx

from tradingagents.config.runtime_settings import get_bool


def _resolve_httpx_ssl_options() -> Dict[str, Any]:
    verify_ssl = get_bool("TA_OPENAI_SSL_VERIFY", "ta_openai_ssl_verify", True)
    ca_bundle = os.getenv("TA_OPENAI_CA_BUNDLE") or os.getenv("OPENAI_CA_BUNDLE")
    client_cert = os.getenv("TA_OPENAI_CLIENT_CERT") or os.getenv("OPENAI_CLIENT_CERT")

    options: Dict[str, Any] = {}
    if not verify_ssl:
        options["verify"] = False
    elif ca_bundle:
        options["verify"] = ca_bundle

    if client_cert:
        options["cert"] = client_cert

    return options


def build_langchain_http_client_kwargs(existing_kwargs: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Return optional ChatOpenAI kwargs for SSL customization."""
    existing_kwargs = existing_kwargs or {}
    if "http_client" in existing_kwargs and "http_async_client" in existing_kwargs:
        return {}

    ssl_options = _resolve_httpx_ssl_options()
    if not ssl_options:
        return {}

    kwargs: Dict[str, Any] = {}
    if "http_client" not in existing_kwargs:
        kwargs["http_client"] = httpx.Client(**ssl_options)
    if "http_async_client" not in existing_kwargs:
        kwargs["http_async_client"] = httpx.AsyncClient(**ssl_options)
    return kwargs


def build_openai_sdk_client_kwargs(existing_kwargs: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Return optional OpenAI SDK kwargs for SSL customization."""
    existing_kwargs = existing_kwargs or {}
    if "http_client" in existing_kwargs:
        return {}

    ssl_options = _resolve_httpx_ssl_options()
    if not ssl_options:
        return {}

    return {
        "http_client": httpx.Client(**ssl_options),
    }
