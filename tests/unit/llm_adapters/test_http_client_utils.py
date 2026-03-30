from tradingagents.llm_adapters import http_client_utils


def test_build_langchain_http_client_kwargs_respects_verify_flag(monkeypatch):
    sync_calls = []
    async_calls = []

    monkeypatch.setenv("TA_OPENAI_SSL_VERIFY", "false")
    monkeypatch.delenv("TA_OPENAI_CA_BUNDLE", raising=False)
    monkeypatch.delenv("OPENAI_CA_BUNDLE", raising=False)
    monkeypatch.delenv("TA_OPENAI_CLIENT_CERT", raising=False)
    monkeypatch.delenv("OPENAI_CLIENT_CERT", raising=False)
    monkeypatch.setattr(
        http_client_utils.httpx,
        "Client",
        lambda **kwargs: sync_calls.append(kwargs) or ("sync", kwargs),
    )
    monkeypatch.setattr(
        http_client_utils.httpx,
        "AsyncClient",
        lambda **kwargs: async_calls.append(kwargs) or ("async", kwargs),
    )

    kwargs = http_client_utils.build_langchain_http_client_kwargs()

    assert kwargs["http_client"][0] == "sync"
    assert kwargs["http_async_client"][0] == "async"
    assert sync_calls == [{"verify": False}]
    assert async_calls == [{"verify": False}]


def test_build_openai_sdk_client_kwargs_prefers_ca_bundle(monkeypatch):
    sync_calls = []

    monkeypatch.delenv("TA_OPENAI_SSL_VERIFY", raising=False)
    monkeypatch.setenv("TA_OPENAI_CA_BUNDLE", "/tmp/custom-ca.pem")
    monkeypatch.setenv("TA_OPENAI_CLIENT_CERT", "/tmp/client-cert.pem")
    monkeypatch.setattr(
        http_client_utils.httpx,
        "Client",
        lambda **kwargs: sync_calls.append(kwargs) or ("sync", kwargs),
    )

    kwargs = http_client_utils.build_openai_sdk_client_kwargs()

    assert kwargs["http_client"][0] == "sync"
    assert sync_calls == [
        {
            "verify": "/tmp/custom-ca.pem",
            "cert": "/tmp/client-cert.pem",
        }
    ]


def test_build_langchain_http_client_kwargs_does_not_override_explicit_clients(monkeypatch):
    monkeypatch.setenv("TA_OPENAI_SSL_VERIFY", "false")

    kwargs = http_client_utils.build_langchain_http_client_kwargs(
        {
            "http_client": "existing-sync",
            "http_async_client": "existing-async",
        }
    )

    assert kwargs == {}


def test_build_openai_sdk_client_kwargs_does_not_override_explicit_client(monkeypatch):
    monkeypatch.setenv("TA_OPENAI_SSL_VERIFY", "false")

    kwargs = http_client_utils.build_openai_sdk_client_kwargs(
        {
            "http_client": "existing-sync",
        }
    )

    assert kwargs == {}
