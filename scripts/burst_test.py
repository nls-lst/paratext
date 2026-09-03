#!/usr/bin/env python3
"""Burst-test a workshop-mode paratext instance.

Simulates a room: N independent browsers, each with its own cookie jar, each
editing a prompt and running a batch of cards at the same moment. Answers the
questions a shared Space raises and one client cannot:

  - does every attendee get their own session, or do cookies collide?
  - does the endpoint hold up when N runs land together, or do we hit provider
    rate limits?
  - does one attendee's round ever show up in another's dataset list?
  - how long does the slowest attendee wait?

Usage:
    python burst_test.py https://host [--attendees 20] [--cards 3]

Read-only on your own data: it only ever creates sessions on the target.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request


class Attendee:
    """One browser: its own cookie jar, its own session."""

    def __init__(self, base: str, n: int, cards: int):
        self.base, self.n, self.cards = base.rstrip("/"), n, cards
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )
        self.session = ""
        self.round = ""
        self.error = ""
        self.seconds = 0.0
        self.polls = 0

    def _call(self, path: str, body: dict | None = None, method: str | None = None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            f"{self.base}{path}", data=data, method=method or ("POST" if data else "GET"),
            headers={"content-type": "application/json"},
        )
        with self.opener.open(req, timeout=180) as r:
            return json.loads(r.read() or "{}")

    def run(self) -> None:
        t0 = time.monotonic()
        try:
            state = self._call("/api/workshop/state")
            self.session = state["session"]
            # Each attendee writes a distinguishable prompt, so a crossed session
            # shows up as somebody else's text.
            prompt = (
                f"Attendee {self.n}. Read this catalogue card and return JSON.\n"
                f"- call_number: the shelfmark.\n- author: the main entry.\n"
                f"- title: the title as printed.\nTranscribe as printed."
            )
            job = self._call("/api/workshop/run", {
                "prompt": prompt,
                "fields": [{"name": "call_number"}, {"name": "author"}, {"name": "title"}],
                "cards": self.cards,
            })
            if "id" not in job:
                raise RuntimeError(job.get("error", "run refused"))
            while job.get("status") == "running":
                time.sleep(1.5)
                self.polls += 1
                job = self._call(f"/api/workshop/job/{job['id']}")
            if job.get("status") == "error":
                raise RuntimeError(job.get("error", "unknown"))
            self.round = job.get("round", "")
            if job.get("failures"):
                self.error = f"{len(job['failures'])} card(s) failed: {job['failures'][0][:80]}"
        except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError, KeyError) as e:
            detail = ""
            if isinstance(e, urllib.error.HTTPError):
                try:
                    detail = json.loads(e.read()).get("error", "")
                except Exception:
                    detail = ""
            self.error = f"{type(e).__name__}: {detail or e}"
        finally:
            self.seconds = time.monotonic() - t0

    def datasets(self) -> list[str]:
        try:
            return [d["name"] for d in self._call("/api/datasets")]
        except Exception:
            return []


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("base", help="e.g. https://mikegsaunders-paratext-review.hf.space")
    ap.add_argument("--attendees", type=int, default=20)
    ap.add_argument("--cards", type=int, default=3)
    args = ap.parse_args()

    print(f"{args.attendees} attendees × {args.cards} cards at {args.base}\n")
    people = [Attendee(args.base, i + 1, args.cards) for i in range(args.attendees)]
    threads = [threading.Thread(target=p.run) for p in people]

    t0 = time.monotonic()
    for t in threads:      # all at once, which is the point
        t.start()
    for t in threads:
        t.join()
    wall = time.monotonic() - t0

    ok = [p for p in people if not p.error]
    failed = [p for p in people if p.error]
    times = sorted(p.seconds for p in ok)

    print(f"wall clock       {wall:6.1f}s")
    print(f"succeeded        {len(ok)}/{len(people)}")
    if times:
        print(f"slowest attendee {times[-1]:6.1f}s")
        print(f"median           {statistics.median(times):6.1f}s")

    sessions = {p.session for p in people if p.session}
    print(f"distinct sessions {len(sessions)}/{len(people)}"
          f"{'  ← COOKIES COLLIDED' if len(sessions) != len(people) else ''}")

    # Isolation: nobody should be able to see anyone else's round.
    rounds = {p.round for p in ok if p.round}
    leaks = []
    for p in ok[:5]:                       # a sample is enough to prove the point
        visible = set(p.datasets())
        others = (rounds - {p.round}) & visible
        if others:
            leaks.append((p.n, sorted(others)))
    print(f"cross-session leaks {len(leaks)}"
          f"{'  ← ' + str(leaks[:2]) if leaks else ''}")

    if failed:
        print(f"\n{len(failed)} failed:")
        seen: dict[str, int] = {}
        for p in failed:
            seen[p.error[:110]] = seen.get(p.error[:110], 0) + 1
        for msg, n in sorted(seen.items(), key=lambda kv: -kv[1]):
            print(f"  ×{n}  {msg}")

    return 1 if failed or leaks or len(sessions) != len(people) else 0


if __name__ == "__main__":
    sys.exit(main())
