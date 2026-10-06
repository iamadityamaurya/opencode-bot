import secrets
import time
from typing import Any

# Telegram hard-caps callback_data at 64 bytes. Session IDs (~30 chars) plus
# permission/model IDs overflow that quickly, so inline buttons carry a short
# opaque token instead of raw identifiers.
_MAX_TOKEN_TTL_SECONDS = 900.0


class CallbackRegistry:
    """Short opaque tokens that stand in for long callback payloads.

    Tokens are single-process, in-memory and TTL-bound. A stale button is
    harmless: resolving an expired token returns ``None`` and the handler
    refuses to act.
    """

    def __init__(self, ttl_seconds: float = _MAX_TOKEN_TTL_SECONDS):
        self.ttl_seconds = ttl_seconds
        self._tokens: dict[str, tuple[str, dict[str, Any], float]] = {}

    def _prune(self):
        now = time.monotonic()
        expired = [tok for tok, (_, _, exp) in self._tokens.items() if exp <= now]
        for tok in expired:
            self._tokens.pop(tok, None)

    def add(self, kind: str, payload: dict[str, Any]) -> str:
        self._prune()
        token = secrets.token_urlsafe(8)
        self._tokens[token] = (kind, payload, time.monotonic() + self.ttl_seconds)
        return token

    def resolve(self, token: str, expected_kind: str | None = None) -> dict[str, Any] | None:
        self._prune()
        entry = self._tokens.get(token)
        if not entry:
            return None
        kind, payload, _ = entry
        if expected_kind and kind != expected_kind:
            return None
        return payload
