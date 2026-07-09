"""model call wrapper: structured output (Pydantic) with plain-JSON fallback,
retry on transient errors, image encoding."""

from __future__ import annotations

import base64
import io
import logging

import stamina
from openai import APIConnectionError, APITimeoutError, InternalServerError, OpenAI
from PIL import Image
from pydantic import BaseModel

logger = logging.getLogger(__name__)

RETRYABLE_ERRORS = (APIConnectionError, APITimeoutError, InternalServerError)


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
    max_tokens: int = 2048,
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
    completion = client.beta.chat.completions.parse(**kwargs)
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
    max_tokens: int = 2048,
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
    content = completion.choices[0].message.content
    if content is None:
        raise ValueError("model returned empty content")
    return content.strip()
