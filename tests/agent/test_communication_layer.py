"""Tests for the optional final-response communication/persona layer."""

from types import SimpleNamespace


class _Choice:
    def __init__(self, content: str):
        self.message = SimpleNamespace(content=content)


class _Response:
    def __init__(self, content: str):
        self.choices = [_Choice(content)]


def _agent(config, soul="Sage style: concise, warm, no em dashes."):
    return SimpleNamespace(
        config=config,
        provider="openai-codex",
        model="gpt-5.5",
        base_url="https://chatgpt.com/backend-api/codex",
        api_key="",
        api_mode="codex_responses",
        platform="telegram",
        session_id="s1",
        soul_content=soul,
        _current_main_runtime=lambda: {
            "provider": "openai-codex",
            "model": "gpt-5.5",
            "base_url": "https://chatgpt.com/backend-api/codex",
            "api_key": "",
            "api_mode": "codex_responses",
        },
    )


def test_disabled_returns_original_without_calling_model(monkeypatch):
    from agent.communication_layer import rewrite_final_response

    def boom(**_kwargs):
        raise AssertionError("communication model should not be called")

    monkeypatch.setattr("agent.communication_layer.call_llm", boom)

    original = "Done. Wrote /tmp/report.md."
    result = rewrite_final_response(_agent({"communication_layer": {"enabled": False}}), original)

    assert result.text == original
    assert result.changed is False
    assert result.reason == "disabled"


def test_rewrite_uses_configured_model_and_preserves_canonical_context(monkeypatch):
    from agent.communication_layer import rewrite_final_response

    calls = []

    def fake_call_llm(**kwargs):
        calls.append(kwargs)
        return _Response("Done. Report is at /tmp/report.md, source: https://example.com.")

    monkeypatch.setattr("agent.communication_layer.call_llm", fake_call_llm)

    original = "The report is at /tmp/report.md. Source: https://example.com."
    result = rewrite_final_response(
        _agent({
            "communication_layer": {
                "enabled": True,
                "provider": "ollama-cloud",
                "model": "gemma4:31b",
                "max_tokens": 400,
                "timeout": 30,
            }
        }),
        original,
    )

    assert result.text == "Done. Report is at /tmp/report.md, source: https://example.com."
    assert result.changed is True
    assert calls[0]["task"] == "communication_layer"
    assert calls[0]["provider"] == "ollama-cloud"
    assert calls[0]["model"] == "gemma4:31b"
    assert calls[0]["main_runtime"]["model"] == "gpt-5.5"
    assert "Preserve every fact" in calls[0]["messages"][0]["content"]
    assert "Speak as the active agent" in calls[0]["messages"][0]["content"]
    assert "not on behalf of the agent" in calls[0]["messages"][0]["content"]
    assert "Sage style" in calls[0]["messages"][1]["content"]


def test_local_ollama_routes_are_rejected_without_model_call(monkeypatch):
    from agent.communication_layer import rewrite_final_response

    def boom(**_kwargs):
        raise AssertionError("local Ollama route must not be called")

    monkeypatch.setattr("agent.communication_layer.call_llm", boom)

    original = "Done. Wrote /tmp/report.md."
    result = rewrite_final_response(
        _agent({
            "communication_layer": {
                "enabled": True,
                "provider": "ollama",
                "model": "llama3.2",
                "base_url": "http://127.0.0.1:11434/v1",
            }
        }),
        original,
    )

    assert result.text == original
    assert result.reason == "missing_model"


def test_kotak_non_cloud_model_is_rejected_without_model_call(monkeypatch):
    from agent.communication_layer import rewrite_final_response

    def boom(**_kwargs):
        raise AssertionError("local Kotak inference route must not be called")

    monkeypatch.setattr("agent.communication_layer.call_llm", boom)

    original = "Done. Wrote /tmp/report.md."
    result = rewrite_final_response(
        _agent({
            "communication_layer": {
                "enabled": True,
                "provider": "ollama-kotak",
                "model": "llama3.1:8b",
                "base_url": "http://100.74.121.4:11434/v1",
            }
        }),
        original,
    )

    assert result.text == original
    assert result.reason == "missing_model"


def test_kotak_cloud_model_suffix_is_allowed(monkeypatch):
    from agent.communication_layer import rewrite_final_response

    calls = []

    def fake_call_llm(**kwargs):
        calls.append(kwargs)
        return _Response("Done. Wrote /tmp/report.md.")

    monkeypatch.setattr("agent.communication_layer.call_llm", fake_call_llm)

    original = "Done. Wrote /tmp/report.md."
    result = rewrite_final_response(
        _agent({
            "communication_layer": {
                "enabled": True,
                "provider": "ollama-kotak",
                "model": "gemma4:31b-cloud",
                "base_url": "http://100.74.121.4:11434/v1",
            }
        }),
        original,
    )

    assert result.text == original
    assert result.reason == "unchanged"
    assert calls[0]["provider"] == "ollama-kotak"
    assert calls[0]["model"] == "gemma4:31b-cloud"


def test_rewrite_tries_configured_cross_provider_fallback(monkeypatch):
    from agent.communication_layer import rewrite_final_response

    calls = []

    def fake_call_llm(**kwargs):
        calls.append((kwargs["provider"], kwargs["model"]))
        if len(calls) == 1:
            raise RuntimeError("primary down")
        return _Response("Done. Report is at /tmp/report.md.")

    monkeypatch.setattr("agent.communication_layer.call_llm", fake_call_llm)

    original = "The report is at /tmp/report.md."
    result = rewrite_final_response(
        _agent({
            "communication_layer": {
                "enabled": True,
                "provider": "ollama-cloud",
                "model": "gemma4:31b",
                "fallback_providers": [
                    {"provider": "ollama-cloud", "model": "gpt-oss:120b"}
                ],
            }
        }),
        original,
    )

    assert result.text == "Done. Report is at /tmp/report.md."
    assert result.changed is True
    assert calls == [("ollama-cloud", "gemma4:31b"), ("ollama-cloud", "gpt-oss:120b")]
    assert result.provider == "ollama-cloud"
    assert result.model == "gpt-oss:120b"


def test_rewrite_rejected_when_required_literals_are_dropped(monkeypatch):
    from agent.communication_layer import rewrite_final_response

    def fake_call_llm(**_kwargs):
        return _Response("Done. The report is ready.")

    monkeypatch.setattr("agent.communication_layer.call_llm", fake_call_llm)

    original = "The report is at /tmp/report.md. Source: https://example.com."
    result = rewrite_final_response(
        _agent({"communication_layer": {"enabled": True, "provider": "ollama-cloud", "model": "gemma4:31b"}}),
        original,
    )

    assert result.text == original
    assert result.changed is False
    assert result.reason == "guard_failed"
    assert "/tmp/report.md" in result.risk_flags
    assert "https://example.com" in result.risk_flags


def test_code_blocks_are_preserved_exactly_or_rewrite_is_rejected(monkeypatch):
    from agent.communication_layer import rewrite_final_response

    def fake_call_llm(**_kwargs):
        return _Response("Run this instead:\n```bash\necho nope\n```")

    monkeypatch.setattr("agent.communication_layer.call_llm", fake_call_llm)

    original = "Run:\n```bash\nhermes moa list\n```"
    result = rewrite_final_response(
        _agent({"communication_layer": {"enabled": True, "provider": "ollama-cloud", "model": "gemma4:31b"}}),
        original,
    )

    assert result.text == original
    assert result.changed is False
    assert "code_block_changed" in result.risk_flags


def test_turn_finalizer_persists_delivered_communication_text():
    import inspect

    from agent import turn_finalizer

    src = inspect.getsource(turn_finalizer.finalize_turn)
    persist_idx = src.index("agent._persist_session")
    comm_idx = src.index("rewrite_final_response")

    assert comm_idx < persist_idx
    assert "communication_layer" in src
    assert "pre_communication_response" in src
    assert "final_response=_pre_communication_response or final_response" not in src
    assert '_tail.get("content") == _pre_communication_response' in src
    assert "assistant_response=final_response" in src
