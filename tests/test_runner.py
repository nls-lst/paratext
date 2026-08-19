"""Model-call wrapper: output-budget diagnostics."""

import paratext.runner as runner


# ── Output-budget exhaustion ─────────────────────────────────────────────────
# A reasoning model can spend the whole max_tokens budget on thinking and return
# nothing. The tokens are billed and counted but never appear in the response, so
# without a bespoke message this reads like the model failed for no reason.
class _Details:
    reasoning_tokens = 2047


class _Usage:
    completion_tokens_details = _Details()


class _Completion:
    usage = _Usage()


def test_length_error_names_reasoning_tokens():
    err = runner._length_error(_Completion(), 2048)
    msg = str(err)
    assert "2048-token output cap" in msg
    assert "2047 of those went on reasoning" in msg
    assert "--max-tokens" in msg
    assert "extra-body" in msg


def test_length_error_without_reasoning_details():
    class _Bare:
        usage = None

    msg = str(runner._length_error(_Bare(), 512))
    assert "512-token output cap" in msg
    assert "reasoning" in msg  # the remedy still mentions it, the count doesn't


def test_default_max_tokens_leaves_room_for_thinking():
    # Guards the regression this fixed: 2048 was too small for any model that
    # reasons before answering.
    assert runner.DEFAULT_MAX_TOKENS >= 8192
