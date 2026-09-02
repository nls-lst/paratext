"""Run a Project end-to-end: iterate samples, call the model, write JSONL."""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path

from openai import OpenAI
from pydantic import BaseModel
from tqdm import tqdm

from .io import (
    append_error,
    append_jsonl,
    preflight_check,
    read_processed_ids,
    read_provenance,
    write_provenance_header,
)
from .projects import Project
from .runner import DEFAULT_MAX_TOKENS, call_plain, call_structured

logger = logging.getLogger(__name__)


def _prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode()).hexdigest()[:12]


def _parse_loose_json(text: str) -> dict | None:
    """Best-effort JSON parse for plain (non-structured) completions."""
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    if "```json" in text:
        a = text.find("```json") + 7
        b = text.find("```", a)
        if b > a:
            try:
                return json.loads(text[a:b].strip())
            except Exception:
                pass
    a, b = text.find("{"), text.rfind("}") + 1
    if a >= 0 and b > a:
        try:
            return json.loads(text[a:b])
        except Exception:
            pass
    return None


def _guard_stale_output(output: Path, header: dict, project: str, re_extract: bool) -> None:
    """Refuse to resume into extractions made with a different prompt or model.

    Resume skips by sample id, so without this a prompt edit re-runs to
    completion having called the model zero times — the change silently lost.
    """
    prior = read_provenance(output)
    if not prior:
        return
    changed = [k for k in ("prompt_hash", "model")
               if prior.get(k) and prior[k] != header.get(k)]
    if not changed:
        return
    if re_extract:
        output.unlink()
        return
    what = " and ".join(c.replace("_hash", "") for c in changed)
    detail = ", ".join(f"{c.replace('_hash', '')} {prior[c]} -> {header.get(c)}"
                       for c in changed)
    raise SystemExit(
        f"The {what} changed since {output} was written ({detail}).\n"
        f"Those records answer a different question, and resume would skip every\n"
        f"sample and call the model zero times. Either:\n"
        f"  paratext run -p {project} --re-extract           # redo them\n"
        f"  paratext run -p {project} --output <new>.jsonl   # keep both"
    )


def run(
    project: Project,
    source: Path,
    output: Path,
    *,
    base_url: str,
    api_key: str,
    model: str,
    limit: int | None = None,
    use_structured: bool = True,
    skip_preflight: bool = False,
    energy: dict | None = None,
    max_tokens: int | None = None,
    extra_body: dict | None = None,
    re_extract: bool = False,
) -> None:
    """Execute the extraction pipeline and write JSONL to `output`.

    Resume keys on sample id, so an existing `output` is topped up rather than
    redone. `re_extract` discards it instead — needed when the prompt or model
    changed, since those records answer a different question.
    """
    if not skip_preflight:
        preflight_check(base_url)

    client = OpenAI(base_url=base_url, api_key=api_key)
    # The project's vLLM-dialect hint is the floor; caller-supplied extra_body
    # (from paratext.toml) layers on top, so a user on another provider can send
    # that provider's reasoning control without the project knowing about it.
    body: dict = {}
    if project.disable_thinking:
        body["chat_template_kwargs"] = {"enable_thinking": False}
    body.update(extra_body or {})
    extra_body = body or None
    max_tokens = max_tokens or project.max_tokens or DEFAULT_MAX_TOKENS

    header = {
        "project": project.name,
        "schema_version": project.schema_version,
        "prompt_hash": _prompt_hash(project.prompt),
        "prompt": project.prompt,
        "model": model,
        "base_url": base_url,
        "max_tokens": max_tokens,
    }
    if energy is not None:
        header["energy"] = energy  # carbon reading captured by --green gating

    _guard_stale_output(Path(output), header, project.name, re_extract)
    write_provenance_header(output, header)
    seen = read_processed_ids(output, id_field="id")
    if seen:
        logger.info("Resuming run — skipping %d already-processed sample(s)", len(seen))

    for sample in tqdm(project.iter_samples(source, limit), unit="sample"):
        if sample.id in seen:
            continue
        # A sample can be pre-classified by iter_samples (e.g. a deterministic
        # verso filter) to skip the model call entirely.
        pre = (sample.metadata or {}).get("preclassified")
        if pre is not None:
            append_jsonl(
                output,
                {
                    "id": sample.id,
                    "extraction": pre,
                    "metadata": sample.metadata,
                    "elapsed_s": 0.0,
                },
            )
            continue
        t0 = time.monotonic()
        try:
            if use_structured:
                parsed: BaseModel = call_structured(
                    client,
                    model=model,
                    prompt=project.prompt,
                    images=sample.images,
                    schema=project.schema,
                    extra_body=extra_body,
                    max_tokens=max_tokens,
                    image_max_size=project.image_max_size,
                    image_quality=project.image_quality,
                )
                extraction = parsed.model_dump()
            else:
                raw = call_plain(
                    client,
                    model=model,
                    prompt=project.prompt,
                    images=sample.images,
                    extra_body=extra_body,
                    max_tokens=max_tokens,
                    image_max_size=project.image_max_size,
                    image_quality=project.image_quality,
                )
                parsed_dict = _parse_loose_json(raw)
                if parsed_dict is None:
                    raise ValueError("Could not parse JSON from model response")
                extraction = parsed_dict
        except Exception as e:
            append_error(output, sample.id, str(e))
            logger.warning("[%s] failed: %s", sample.id, e)
            continue
        elapsed = time.monotonic() - t0
        record = {
            "id": sample.id,
            "extraction": extraction,
            "metadata": sample.metadata,
            "elapsed_s": round(elapsed, 3),
        }
        append_jsonl(output, record)

    for notice in getattr(project.source, "notices", []):
        logger.warning("%s", notice)
        print(f"\n!  {notice}")
