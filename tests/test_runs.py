"""Background runs and their caps (workshop mode)."""

import threading
import time

import pytest

from paratext.review.runs import Job, Runs, workshop_project


def test_workshop_project_builds_from_typed_fields():
    p = workshop_project("demo", "Read it.", [{"name": "Title"}, {"name": "page count"}])
    assert p.name == "demo" and p.prompt == "Read it."
    assert list(p.schema.model_fields) == ["title", "page_count"]


def test_job_serialises_for_the_browser():
    j = Job(id="abc", total=5, done=2)
    d = j.as_dict()
    assert d["done"] == 2 and d["total"] == 5 and d["status"] == "running"


def test_start_runs_the_work_and_marks_it_done():
    runs = Runs()
    finished = threading.Event()
    job = runs.start("s1", 2, lambda j: (setattr(j, "done", 2), finished.set()))
    assert finished.wait(5)
    for _ in range(50):
        if runs.get(job.id).status == "done":
            break
        time.sleep(0.02)
    assert runs.get(job.id).status == "done"


def test_a_failing_job_reports_the_error_not_a_crash():
    runs = Runs()

    def boom(job):
        raise RuntimeError("endpoint refused")

    job = runs.start("s1", 1, boom)
    for _ in range(50):
        if runs.get(job.id).status != "running":
            break
        time.sleep(0.02)
    got = runs.get(job.id)
    assert got.status == "error" and "endpoint refused" in got.error


def test_runs_are_capped_per_session():
    runs = Runs(max_runs=2)
    for _ in range(2):
        runs.start("s1", 1, lambda j: None)
    with pytest.raises(ValueError, match="used its 2 runs"):
        runs.start("s1", 1, lambda j: None)


def test_the_cap_is_per_session_not_global():
    runs = Runs(max_runs=1)
    runs.start("s1", 1, lambda j: None)
    runs.start("s2", 1, lambda j: None)          # a different attendee is unaffected
    with pytest.raises(ValueError):
        runs.start("s1", 1, lambda j: None)


def test_active_tracks_only_the_running_job():
    runs = Runs()
    done = threading.Event()
    runs.start("s1", 1, lambda j: done.set())
    assert done.wait(5)
    for _ in range(50):
        if runs.active("s1") is None:
            break
        time.sleep(0.02)
    assert runs.active("s1") is None
