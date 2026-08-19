"""model call wrapper: structured output (Pydantic) with plain-JSON fallback,
retry on transient errors, image encoding."""

from __future__ import annotations

import base64
import io
import logging

import stamina
from openai import (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    LengthFinishReasonError,
    OpenAI,
)
from PIL import Image
from pydantic import BaseModel

logger = logging.getLogger(__name__)

RETRYABLE_ERRORS = (APIConnectionError, APITimeoutError, InternalServerError)

# Output-token ceiling per call. Sized for a reasoning model, not for the
# extraction itself: a card's JSON is a few hundred tokens, but a model that
# thinks first spends its budget on reasoning tokens the caller never sees, and
# a truncated completion parses as nothing at all. You are billed for tokens
# generated, not for the cap, so a generous ceiling costs nothing on a model
# that stops early — and rescues one that doesn't.
DEFAULT_MAX_TOKENS = 8192


def _length_error(completion, max_tokens: int) -> ValueError:
    """Explain a completion that ran out of output budget.

    Worth a bespoke message because the usual cause is invisible: reasoning
    tokens are billed and counted but never appear in the response, so the
    failure looks like the model returned nothing for no reason.
    """
    usage = getattr(completion, "usage", None)
    details = getattr(usage, "completion_tokens_details", None)
    reasoning = getattr(details, "reasoning_tokens", 0) or 0
    msg = f"model hit the {max_tokens}-token output cap before finishing"
    if reasoning:
        msg += f" — {reasoning} of those went on reasoning, leaving nothing for the answer"
    return ValueError(
        f"{msg}.\n"
        f"  Raise it with --max-tokens N (or `max-tokens` in paratext.toml),\n"
        f"  or turn reasoning off for your provider via "
        f"[project.<name>.extra-body] — note that the built-in\n"
        f"  `disable_thinking` speaks vLLM's dialect only. See docs/configuration.md."
    )


def encode_image(img: Image.Image, max_size: int = 1024, quality: int = 85) -> str:
    """Resize, JPEG-encode, base64. Returns a data URI ready for OpenAI image_url."""
    img = img.copy()
    img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()


def build_user_message(
    prompt: str, images: list[Image.Image], max_size: int = 1024, quality: int = 85
) -> dict:
    parts: list[dict] = [{"type": "text", "text": prompt}]
    for img in images:
        parts.append(
            {"type": "image_url", "image_url": {"url": encode_image(img, max_size, quality)}}
        )
    return {"role": "user", "content": parts}


@stamina.retry(on=RETRYABLE_ERRORS, attempts=3, wait_initial=2.0, wait_max=30.0)
def call_structured(
    client: OpenAI,
    model: str,
    prompt: str,
    images: list[Image.Image],
    schema: type[BaseModel],
    extra_body: dict | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    temperature: float = 0.0,
    image_max_size: int = 1024,
    image_quality: int = 85,
) -> BaseModel:
    """Use the Pydantic response_format API to get a typed result."""
    kwargs: dict = {
        "model": model,
        "messages": [build_user_message(prompt, images, image_max_size, image_quality)],
        "response_format": schema,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if extra_body:
        kwargs["extra_body"] = extra_body
    try:
        completion = client.beta.chat.completions.parse(**kwargs)
    except LengthFinishReasonError as exc:
        raise _length_error(exc.completion, max_tokens) from exc
    parsed = completion.choices[0].message.parsed
    if parsed is None:
        raise ValueError("Structured output returned None — model may not support response_format")
    return parsed


@stamina.retry(on=RETRYABLE_ERRORS, attempts=3, wait_initial=2.0, wait_max=30.0)
def call_plain(
    client: OpenAI,
    model: str,
    prompt: str,
    images: list[Image.Image],
    extra_body: dict | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    temperature: float = 0.0,
    image_max_size: int = 1024,
    image_quality: int = 85,
) -> str:
    """Plain chat completion; caller handles JSON parsing."""
    kwargs: dict = {
        "model": model,
        "messages": [build_user_message(prompt, images, image_max_size, image_quality)],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if extra_body:
        kwargs["extra_body"] = extra_body
    completion = client.chat.completions.create(**kwargs)
    # No LengthFinishReasonError here — the plain API doesn't parse, so a
    # truncated completion arrives looking like ordinary content and only fails
    # later, in the caller's JSON parse.
    if completion.choices[0].finish_reason == "length":
        raise _length_error(completion, max_tokens)
    content = completion.choices[0].message.content
    if content is None:
        raise ValueError("model returned empty content")
    return content.strip()
