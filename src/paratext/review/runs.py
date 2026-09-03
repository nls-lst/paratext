"""Background extraction runs for workshop mode.

`extract.run` is built for a sweep: resume, tqdm, a whole collection. A workshop
run is five cards that somebody is watching, so this is a small loop that
reports progress per card and can be polled.

One job per session at a time. A run costs money, so the caps here are the
thing standing between a public Space and someone's credit balance.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from openai import OpenAI

from ..extract import _prompt_hash
from ..io import append_jsonl, write_provenance_header
from ..packaging import package
from ..projects import Project
from ..runner import call_structured
from ..sources import image_source
from ..workshop import build_schema

logger = logging.getLogger(__name__)

MAX_CARDS = 8          # per run
MAX_RUNS_PER_SESSION = 40


@dataclass
class Job:
    id: str
    total: int
    done: int = 0
    status: str = "running"      # running | done | error
    error: str = ""
    round_name: str = ""
    failures: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "total": self.total,
            "done": self.done,
            "status": self.status,
            "error": self.error,
            "round": self.round_name,
            "failures": self.failures,
        }


class Runs:
    """Tracks one job per session, and how many runs a session has spent."""

    def __init__(self, max_runs: int = MAX_RUNS_PER_SESSION):
        self._jobs: dict[str, Job] = {}
        self._by_session: dict[str, str] = {}
        self._spent: dict[str, int] = {}
        self._lock = threading.Lock()
        self.max_runs = max_runs

    def active(self, session_id: str) -> Job | None:
        with self._lock:
            job = self._jobs.get(self._by_session.get(session_id, ""))
        return job if job and job.status == "running" else None

    def get(self, job_id: str) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def spent(self, session_id: str) -> int:
        with self._lock:
            return self._spent.get(session_id, 0)

    def start(self, session_id: str, total: int, work) -> Job:
        """Register a job and run `work(job)` on a thread."""
        with self._lock:
            if self._spent.get(session_id, 0) >= self.max_runs:
                raise ValueError(
                    f"This session has used its {self.max_runs} runs. "
                    f"Reload with a fresh session to continue."
                )
            self._spent[session_id] = self._spent.get(session_id, 0) + 1
            job = Job(id=uuid.uuid4().hex[:12], total=total)
            self._jobs[job.id] = job
            self._by_session[session_id] = job.id

        def target():
            try:
                work(job)
                job.status = "done" if job.status == "running" else job.status
            except Exception as e:                      # noqa: BLE001 — surfaced to the UI
                logger.exception("workshop run failed")
                job.status, job.error = "error", str(e)

        threading.Thread(target=target, daemon=True).start()
        return job


def workshop_project(name: str, prompt: str, fields: list[dict]) -> Project:
    """A Project assembled from what the attendee typed, not from an installed
    package."""
    return Project(
        name=name,
        schema_version="v1",
        prompt=prompt,
        schema=build_schema(fields),
        source=image_source(),
    )


def extract_and_package(
    job: Job,
    *,
    proj: Project,
    source: Path,
    output: Path,
    review_out: Path,
    base_url: str,
    api_key: str,
    model: str,
    cards: int,
) -> None:
    """Run the model over `cards` samples, then package a round. Updates `job`
    as it goes so the browser can draw a progress bar."""
    client = OpenAI(base_url=base_url, api_key=api_key)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()          # a workshop run is always a fresh round
    write_provenance_header(output, {
        "project": proj.name,
        "schema_version": proj.schema_version,
        "prompt_hash": _prompt_hash(proj.prompt),
        "prompt": proj.prompt,
        "model": model,
        "base_url": base_url,
    })

    for sample in proj.source.iter_samples(source, cards):
        t0 = time.monotonic()
        try:
            parsed = call_structured(
                client, model=model, prompt=proj.prompt, images=sample.images,
                schema=proj.schema, image_max_size=proj.image_max_size,
                image_quality=proj.image_quality,
            )
            append_jsonl(output, {
                "id": sample.id,
                "extraction": parsed.model_dump(),
                "metadata": sample.metadata,
                "elapsed_s": round(time.monotonic() - t0, 3),
            })
        except Exception as e:                          # noqa: BLE001
            job.failures.append(f"{sample.id}: {e}")
            logger.warning("[%s] failed: %s", sample.id, e)
        finally:
            job.done += 1

    if job.done and len(job.failures) == job.done:
        raise RuntimeError(f"every card failed — {job.failures[0]}")

    kept, _ = package(output, review_out, proj.name, fresh=True, proj=proj)
    job.round_name = review_out.name
    if not kept:
        raise RuntimeError("nothing survived packaging")
