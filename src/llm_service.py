"""Anthropic Claude client abstraction for the procurement assistant.

Every function here fails soft: on any error (missing key, missing package,
network failure, bad response) callers get None back and must fall back to
the deterministic analytics layer. The LLM is used ONLY to interpret and
narrate results that were already computed elsewhere — it never computes
scores, ranks, prices, or any numeric value itself.
"""
from __future__ import annotations

import json
import os

DEFAULT_MODEL = "claude-sonnet-5"

SYSTEM_PROMPT = (
    "You are a procurement analyst assistant embedded in an internal vendor evaluation tool. "
    "You explain and interpret vendor evaluation results that have ALREADY been computed by "
    "deterministic code — you never calculate, estimate, or invent scores, ranks, prices, or any "
    "numeric value yourself. Only use the numbers given to you in the DATA block; treat them as "
    "ground truth and never contradict or 'correct' them. If something is not present in DATA, say "
    "it is not available rather than guessing. Never state or imply that a vendor has been approved "
    "or selected — every procurement decision requires explicit human approval, and DATA already "
    "reflects that this is a recommendation only. Be concise and analytical, like a senior "
    "procurement analyst briefing a colleague. Clearly distinguish factual figures (from DATA) from "
    "your own advisory interpretation."
)


def get_api_key() -> str | None:
    key = os.environ.get("ANTHROPIC_API_KEY")
    return key if key else None


def _get_client(api_key: str):
    try:
        import anthropic
    except ImportError:
        return None
    try:
        return anthropic.Anthropic(api_key=api_key)
    except Exception:
        return None


def get_client(api_key: str | None = None):
    """Public accessor for a ready-to-use Anthropic client, or None on any failure."""
    api_key = api_key or get_api_key()
    if not api_key:
        return None
    return _get_client(api_key)


def get_model() -> str:
    return os.environ.get("CLAUDE_MODEL", DEFAULT_MODEL)


def is_available(api_key: str | None = None) -> bool:
    api_key = api_key or get_api_key()
    return _get_client(api_key) is not None if api_key else False


def interpret(
    question: str,
    data: dict,
    history: list[tuple[str, str]] | None = None,
    api_key: str | None = None,
) -> str | None:
    """Ask Claude to interpret/narrate an already-computed `data` bundle for `question`.

    Returns None on any failure (missing key, package, network, bad response) so the
    caller can fall back to its deterministic rule-based text.
    """
    api_key = api_key or get_api_key()
    if not api_key:
        return None
    client = _get_client(api_key)
    if client is None:
        return None

    messages = []
    for role, msg in (history or [])[-6:]:
        messages.append({"role": "user" if role == "user" else "assistant", "content": msg})

    try:
        data_json = json.dumps(data, indent=2, default=str)
    except Exception:
        data_json = str(data)

    messages.append(
        {
            "role": "user",
            "content": (
                f"DATA (ground truth, already computed — do not recompute, alter, or contradict "
                f"any value in it):\n{data_json}\n\nQUESTION: {question}"
            ),
        }
    )

    try:
        model = get_model()
        response = client.messages.create(
            model=model,
            max_tokens=700,
            system=SYSTEM_PROMPT,
            messages=messages,
        )
        return response.content[0].text.strip()
    except Exception:
        return None


def narrate(prompt: str, api_key: str | None = None, max_tokens: int = 300) -> str | None:
    """Generic single-shot Claude call for standalone narrative text. Returns None on any failure."""
    api_key = api_key or get_api_key()
    if not api_key:
        return None
    client = _get_client(api_key)
    if client is None:
        return None
    try:
        model = get_model()
        message = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip()
    except Exception:
        return None
