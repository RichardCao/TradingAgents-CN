from tradingagents.llm_adapters.dashscope_openai_adapter import ChatDashScopeOpenAI
from tradingagents.llm_adapters.openai_compatible_base import ChatCustomOpenAI


def test_custom_openai_adapter_passes_http_clients(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        "tradingagents.llm_adapters.openai_compatible_base.build_langchain_http_client_kwargs",
        lambda existing_kwargs=None: {
            "http_client": "sync-client",
            "http_async_client": "async-client",
        },
    )
    monkeypatch.setattr(
        "langchain_openai.ChatOpenAI.__init__",
        lambda self, **kwargs: captured.update(kwargs) or None,
    )

    ChatCustomOpenAI(
        model="gpt-5.4",
        api_key="sk-test-placeholder-001",
        base_url="https://api.openai.com/v1",
    )

    assert captured["http_client"] == "sync-client"
    assert captured["http_async_client"] == "async-client"
    assert captured["model"] == "gpt-5.4"


def test_dashscope_adapter_passes_http_clients(monkeypatch):
    captured = {}

    monkeypatch.setattr(
        "tradingagents.llm_adapters.dashscope_openai_adapter.build_langchain_http_client_kwargs",
        lambda existing_kwargs=None: {
            "http_client": "sync-client",
            "http_async_client": "async-client",
        },
    )
    monkeypatch.setattr(
        "langchain_openai.ChatOpenAI.__init__",
        lambda self, **kwargs: captured.update(kwargs) or None,
    )

    ChatDashScopeOpenAI(
        model="qwen-turbo",
        api_key="sk-test-placeholder-001",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    assert captured["http_client"] == "sync-client"
    assert captured["http_async_client"] == "async-client"
    assert captured["model"] == "qwen-turbo"
