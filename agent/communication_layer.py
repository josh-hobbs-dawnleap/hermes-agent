"""Optional final-response communication/persona rewrite layer.

The main agent model remains the canonical reasoning/tool authority. When this
layer runs successfully, its text becomes the delivered and canonical assistant
final message. The raw pre-communication text is retained only as debug metadata
by the caller. The layer fails open to the original text if the configured
communication model is unavailable or preservation guards detect factual drift.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging
import re
from typing import Any

from agent.auxiliary_client import call_llm, extract_content_or_reasoning

logger = logging.getLogger(__name__)


@dataclass
class RewriteResult:
    text: str
    changed: bool = False
    reason: str = "unchanged"
    provider: str = ""
    model: str = ""
    risk_flags: list[str] = field(default_factory=list)


_URL_RE = re.compile(r"https?://[^\s)\]}>'\"]+")
_PATH_RE = re.compile(r"(?<![\w.-])(?:~|/|\./|\.\./)[\w./@%+,:=-]+")
_COMMANDISH_RE = re.compile(
    r"(?m)(?:^|[`\n])((?:hermes|python3?|uv|git|sudo|systemctl|docker|curl|ssh|scp|rsync|npm|pnpm|node)\s+[^`\n]+)"
)
_CODE_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)
_NUMBER_RE = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?(?:[%xX]|[kKmMgGtTpP][bB]?)?(?![\w.])")
_WARNING_TERMS = (
    "failed",
    "error",
    "warning",
    "not verified",
    "could not verify",
    "approval",
    "blocked",
    "secret",
    "credential",
)


def _cfg_enabled(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes", "on", "enabled"}
    return False


def _communication_config(agent: Any) -> dict[str, Any]:
    cfg = getattr(agent, "config", None) or {}
    raw = cfg.get("communication_layer") or cfg.get("communication") or {}
    return raw if isinstance(raw, dict) else {}


def _platform_allowed(config: dict[str, Any], platform: str) -> bool:
    platforms = config.get("platforms")
    if not platforms:
        return True
    if isinstance(platforms, str):
        platforms = [p.strip() for p in platforms.split(",")]
    if not isinstance(platforms, (list, tuple, set)):
        return True
    normalized = {str(p).strip().lower() for p in platforms if str(p).strip()}
    return not normalized or platform.strip().lower() in normalized


def _literal_requirements(text: str) -> list[str]:
    values: list[str] = []
    for regex in (_URL_RE, _PATH_RE, _COMMANDISH_RE):
        for match in regex.findall(text or ""):
            literal = match if isinstance(match, str) else match[0]
            literal = literal.strip().strip(".,;:")
            if literal and literal not in values:
                values.append(literal)
    # Preserve distinctive numbers. Very small prose numbers create too many
    # false rejects, so keep this to values likely to be operationally relevant.
    for literal in _NUMBER_RE.findall(text or ""):
        if any(ch.isdigit() for ch in literal) and len(literal.strip("-%xXkKmMgGtTpPbB")) >= 2:
            if literal not in values:
                values.append(literal)
    return values


def _code_blocks(text: str) -> list[str]:
    return [m.group(0) for m in _CODE_BLOCK_RE.finditer(text or "")]


def _guard_rewrite(original: str, rewritten: str, *, preserve_code_blocks: bool = True) -> list[str]:
    flags: list[str] = []
    for literal in _literal_requirements(original):
        if literal and literal not in rewritten:
            flags.append(literal)

    if preserve_code_blocks:
        original_blocks = _code_blocks(original)
        rewritten_blocks = _code_blocks(rewritten)
        for block in original_blocks:
            if block not in rewritten_blocks:
                flags.append("code_block_changed")
                break

    lower_rewritten = rewritten.lower()
    lower_original = original.lower()
    for term in _WARNING_TERMS:
        if term in lower_original and term not in lower_rewritten:
            flags.append(f"dropped_warning:{term}")

    return flags


def _style_context(agent: Any, max_chars: int) -> str:
    candidates = [
        getattr(agent, "soul_content", ""),
        getattr(agent, "_cached_system_prompt", ""),
    ]
    for candidate in candidates:
        text = str(candidate or "").strip()
        if text:
            return text[:max_chars]
    return "Preserve the active agent's configured SOUL/persona style, but keep the answer concise."


def _main_runtime(agent: Any) -> dict[str, Any] | None:
    fn = getattr(agent, "_current_main_runtime", None)
    if callable(fn):
        try:
            runtime = fn()
        except Exception:
            return None
        return runtime if isinstance(runtime, dict) else None
    return None


def _is_local_ollama_route(route: dict[str, Any]) -> bool:
    provider = str(route.get("provider") or "").strip().lower()
    base_url = str(route.get("base_url") or "").strip().lower()
    model = str(route.get("model") or "").strip().lower()

    if provider in {"ollama-cloud", "ollama-kotak", "ollama-kotak-cloud"}:
        return False
    if provider == "ollama" and ":cloud" in model:
        return False
    if provider == "ollama" and (
        not base_url
        or "127.0.0.1" in base_url
        or "localhost" in base_url
        or ":11434" in base_url
    ):
        return True
    return False


def _candidate_routes(config: dict[str, Any]) -> list[dict[str, Any]]:
    routes: list[dict[str, Any]] = []
    primary = {
        "provider": str(config.get("provider") or "").strip(),
        "model": str(config.get("model") or "").strip(),
        "base_url": str(config.get("base_url") or "").strip(),
        "api_key": str(config.get("api_key") or "").strip(),
        "api_mode": str(config.get("api_mode") or "").strip(),
        "timeout": config.get("timeout"),
    }
    if primary["provider"] and primary["model"]:
        routes.append(primary)

    raw_fallbacks = config.get("fallback_providers") or config.get("fallback_chain") or []
    if isinstance(raw_fallbacks, dict):
        raw_fallbacks = [raw_fallbacks]
    if isinstance(raw_fallbacks, list):
        for entry in raw_fallbacks:
            if not isinstance(entry, dict):
                continue
            provider = str(entry.get("provider") or "").strip()
            model = str(entry.get("model") or "").strip()
            if not provider or not model:
                continue
            routes.append({
                "provider": provider,
                "model": model,
                "base_url": str(entry.get("base_url") or "").strip(),
                "api_key": str(entry.get("api_key") or "").strip(),
                "api_mode": str(entry.get("api_mode") or entry.get("transport") or "").strip(),
                "timeout": entry.get("timeout", config.get("timeout")),
            })
    return routes


def rewrite_final_response(agent: Any, final_response: str) -> RewriteResult:
    """Rewrite finalized delivery text through a narrow persona layer.

    If this returns a changed response, that text is the canonical assistant
    final message. Callers may retain the original final_response only as debug
    metadata, never as transcript/session/memory content.
    """

    original = str(final_response or "")
    if not original.strip():
        return RewriteResult(original, reason="empty")

    config = _communication_config(agent)
    if not _cfg_enabled(config.get("enabled", False)):
        return RewriteResult(original, reason="disabled")

    platform = str(getattr(agent, "platform", "") or "")
    if not _platform_allowed(config, platform):
        return RewriteResult(original, reason="platform_disabled")

    max_chars = int(config.get("max_chars") or 12000)
    if max_chars > 0 and len(original) > max_chars:
        return RewriteResult(original, reason="too_long")

    routes = [route for route in _candidate_routes(config) if not _is_local_ollama_route(route)]
    if not routes:
        return RewriteResult(original, reason="missing_model")

    style = _style_context(agent, int(config.get("style_context_chars") or 2500))
    max_tokens = int(config.get("max_tokens") or 700)
    preserve_code_blocks = config.get("preserve_code_blocks", True) is not False

    system = (
        "You are a communication/persona rewrite layer for Hermes Agent. "
        "Rewrite style only. Preserve every fact, number, URL, file path, command, "
        "code block, warning, uncertainty level, tool result, and decision. "
        "Do not add new claims. Do not remove blockers, approvals, failed/verified "
        "language, security warnings, or file-mutation warnings. Keep it concise. "
        "If the answer contains code blocks, preserve them exactly. "
        "Speak as the active agent, in first person, using the SOUL/personality/style "
        "context below. Do not paraphrase, summarize, or narrate the answer as a third "
        "party describing what the agent said; write it directly as the agent's own "
        "reply, not on behalf of the agent. Return only the rewritten answer."
    )
    user = (
        "Agent style context:\n"
        f"{style}\n\n"
        "Canonical finalized answer to rewrite without changing substance:\n"
        f"{original}"
    )

    last_error = None
    main_runtime = _main_runtime(agent)
    for route in routes:
        provider = route["provider"]
        model = route["model"]
        try:
            response = call_llm(
                task="communication_layer",
                provider=provider,
                model=model,
                base_url=route.get("base_url") or "",
                api_key=route.get("api_key") or "",
                api_mode=route.get("api_mode") or "",
                main_runtime=main_runtime,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=float(config.get("temperature", 0.2)),
                max_tokens=max_tokens,
                timeout=float(route.get("timeout") or config.get("timeout") or 45),
            )
            rewritten = extract_content_or_reasoning(response).strip()
        except Exception as exc:
            last_error = exc
            logger.info(
                "communication layer route %s/%s failed: %s",
                provider,
                model,
                exc,
            )
            continue

        if not rewritten:
            last_error = RuntimeError("empty rewrite")
            continue

        risk_flags = _guard_rewrite(
            original,
            rewritten,
            preserve_code_blocks=preserve_code_blocks,
        )
        if risk_flags:
            logger.info("communication layer rewrite rejected: %s", risk_flags[:10])
            return RewriteResult(
                original,
                reason="guard_failed",
                provider=provider,
                model=model,
                risk_flags=risk_flags,
            )

        return RewriteResult(
            rewritten,
            changed=rewritten != original,
            reason="rewritten" if rewritten != original else "unchanged",
            provider=provider,
            model=model,
        )

    if last_error is not None:
        logger.info("communication layer rewrite failed after fallbacks: %s", last_error)
    first = routes[0]
    return RewriteResult(
        original,
        reason="model_error" if last_error is not None else "empty_rewrite",
        provider=first.get("provider", ""),
        model=first.get("model", ""),
    )
