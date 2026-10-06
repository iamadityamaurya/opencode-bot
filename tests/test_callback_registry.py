from opencode_telegram.bot.callbacks import CallbackRegistry


def test_token_round_trip():
    registry = CallbackRegistry()
    token = registry.add("permission", {"session_id": "ses_1", "permission_id": "per_1"})
    assert len(f"perm:{token}:approve") <= 64
    payload = registry.resolve(token, expected_kind="permission")
    assert payload == {"session_id": "ses_1", "permission_id": "per_1"}


def test_token_kind_is_enforced():
    registry = CallbackRegistry()
    token = registry.add("model", {"session_id": "ses_1"})
    assert registry.resolve(token, expected_kind="permission") is None
    assert registry.resolve(token, expected_kind="model") is not None


def test_expired_token_is_rejected():
    registry = CallbackRegistry(ttl_seconds=-1)
    token = registry.add("permission", {"session_id": "ses_1"})
    assert registry.resolve(token, expected_kind="permission") is None


def test_unknown_token_is_rejected():
    registry = CallbackRegistry()
    assert registry.resolve("nope", expected_kind="permission") is None
