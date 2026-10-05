import pytest
from opencode_telegram.bot.authorization import is_user_authorized

def test_is_user_authorized_allowed():
    allowed = {12345, 67890}
    assert is_user_authorized(12345, allowed) is True
    assert is_user_authorized(67890, allowed) is True

def test_is_user_authorized_denied():
    allowed = {12345, 67890}
    assert is_user_authorized(99999, allowed) is False
    assert is_user_authorized(None, allowed) is False
