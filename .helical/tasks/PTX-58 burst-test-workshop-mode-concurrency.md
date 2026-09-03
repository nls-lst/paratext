---
id: PTX-58
title: Burst-test workshop-mode concurrency
status: done
horizon: now
flow: clear
labels:
  - tests
created: '2026-09-03'
updated: '2026-09-03'
---

Workshop mode had only ever been driven by one client, leaving the question a
shared instance actually raises unanswered: what happens when a room presses Run
at the same moment.

`scripts/burst_test.py` simulates N browsers with independent cookie jars, all
starting together, and reports wall clock, median and slowest attendee, whether
every attendee got a distinct session, and whether any attendee can see another's
round.

Against the deployed Space, 20 attendees × 3 cards: 20/20 succeeded, 20 distinct
sessions, no cross-session leaks, median 8.8s, slowest 37.6s, about 1.3p. The
spread between median and slowest is provider-side queuing.
