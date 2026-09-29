from career_copilot.core.errors import CopilotError, LLMError


def _all_subclasses(cls: type) -> set[type]:
    """Every descendant, not just direct children."""
    subs = set(cls.__subclasses__())
    return subs | {d for s in subs for d in _all_subclasses(s)}


def test_every_subclass_defines_its_own_user_message():
    for cls in _all_subclasses(CopilotError):
        assert cls.user_message != CopilotError.user_message, (
            f"{cls.__name__} still uses the base user_message"
        )


def test_correlation_id_is_generated():
    err = LLMError("boom")
    assert len(err.correlation_id) == 8
    assert int(err.correlation_id, 16)  # valid hex


def test_user_message_never_leaks_detail():
    err = LLMError("failed calling https://openrouter.ai/api/v1 with key sk-or-v1-abc123")
    assert "openrouter" not in err.user_message
    assert "sk-or" not in err.user_message
    assert "openrouter" in str(err)
