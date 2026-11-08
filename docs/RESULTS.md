# Results

Measured numbers, newest first. Each section says how it was measured so it can be re-run.

## M4 — Load test with simulated concurrent callers (2026-11-08)

**Question (D61, D66):** how many calls at once can the system take, and what breaks first:
our code (session, guard, Redis notebook, SQLite bookings, audit log) or the model server?

**Setup:** `tools/load_test.py`. Each level starts N scripted callers together; every caller
wants a different free 30-minute slot in the next 7 days and runs up to 4 turns ("<day> ko
<time> baje men's haircut chahiye, naam X, number Y" → "haan, book kar do" → "haan" →
"thank you"). Success = a booking saved with the caller's phone. Each level gets a fresh
schedule. Real Redis (db 1/2), a real SQLite file, the real audit log. Two model backends
behind the same interface: an **instant fake model** that always follows the ideal tool flow
(so the numbers isolate our code), and the **real local model** (`mlx_lm.server` 0.32,
Qwen3.5-9B-4bit, defaults: 8 prompts and 32 decodes batched, 10 prompt caches; 30 s client
timeout; 5-minute budget per level). Raw rows: `results/m4_load_fake.csv`,
`results/m4_load_real.csv`.

### Our code alone (instant fake model)

| Callers at once | Bookings made | Median turn | p95 turn | Turns/min | Fallbacks | Stuck | Errors | Wall time |
|---|---|---|---|---|---|---|---|---|
| 1 | 1/1 | 0.00 s | 0.00 s | 15,312 | 0 | 0 | 0 | 0.0 s |
| 10 | 10/10 | 0.02 s | 0.03 s | 26,086 | 0 | 0 | 0 | 0.0 s |
| 50 | 50/50 | 0.13 s | 0.14 s | 19,250 | 0 | 0 | 0 | 0.3 s |
| 100 | 100/100 | 0.24 s | 0.28 s | 21,986 | 0 | 0 | 0 | 0.5 s |

### Whole system (real local model)

Server with default flags (8 prompts / 32 decodes batched), 30 s client timeout:

| Callers at once | Bookings made | Median turn | p95 turn | Fallbacks | Cached share | What happened |
|---|---|---|---|---|---|---|
| 1 | 1/1 | 9.44 s | 10.30 s | 0/3 | 89% | normal: check, propose, read-back, yes → booked |
| 10 | 0/10 | 2.71 s | 88.24 s | 40/40 | 96% | all 10 first turns timed out (30 s + retry); then the GPU ran out of memory and the server's generation thread died |
| 50 | 0/50 | 0.13 s | 0.32 s | 200/200 | n/a | server answered every completion with 404 in 1 ms (dead generation thread) |
| 100 | 0/100 | 0.26 s | 0.48 s | 400/400 | n/a | same; it never recovered until restarted |

Server log at the moment of failure: `[METAL] Command buffer execution failed: Insufficient
Memory (kIOGPUCommandBufferCallbackErrorOutOfMemory)` → `generation thread died`. After
that `GET /v1/models` still worked, so a health check on that endpoint would have said
"healthy" while every call was failing.

Server with gentler batching (`--prompt-concurrency 2 --decode-concurrency 8`), 150 s client
timeout, so queueing shows up as latency instead of as timeouts:

| Callers at once | Bookings made | Median turn | p95 turn | Turns/min | Fallbacks | Cached share | Wall time |
|---|---|---|---|---|---|---|---|
| 1 | 1/1 | 6.70 s | 8.24 s | 12 | 0/3 | 70% | 14.9 s |
| 2 | 2/2 | 7.51 s | 11.26 s | 18 | 0/6 | 89% | 19.7 s |
| 5 | 5/5 | 14.85 s | 25.39 s | 22 | 0/15 | 89% | 40.3 s |
| 10 | 9/10 | 36.55 s | 53.71 s | 16 | 0/31 | 89% | 119.6 s |

The server survived this run (no errors in its log). The one caller of ten who was not
booked hit a false "booked" claim from the model, which the claim check replaced with the
read-back; the caller's scripted lines ran out before a second yes. Raw rows:
`results/m4_load_real_pc2.csv`.

### Findings

1. **Our code is not the limit.** With an instant model, 100 simultaneous callers all got
   booked in half a second with no errors; the session/guard/Redis/SQLite layer runs
   ~20,000 turns a minute on one Mac process. The call-worker layer can scale horizontally
   as D32 assumes; the model is the bottleneck.
2. **The load test found a real bug before any caller did:** the SQLite booking store
   shared one connection across threads. At 10 concurrent callers, 9 of 10 failed with
   `sqlite3.InterfaceError` / `IndexError`. Fixed with one connection per thread and a
   30 s busy timeout, keeping `BEGIN IMMEDIATE` so two callers can never book the same
   slot; a 32-thread race test now guards it (`tests/test_guard.py`).
3. **Lost races are handled, not hidden.** When two callers proposed the same slot at the
   same moment, both heard the read-back, one booking succeeded and the other caller was
   told the time was just taken and offered another, with the refusal in the audit log.
4. **This Mac's limit is about 2 simultaneous calls, and it dies at 10 with default
   settings.** One caller: ~7–9 s per turn (already far from the ~1 s goal, D60). Two
   callers: barely slower. Five: turns double to ~15 s. Ten: ~37 s a turn, 54 s at p95,
   which no phone caller would wait for. Throughput peaks around 20 model turns a minute
   whatever the concurrency: the GPU is simply busy. D66 confirmed: real numbers at 50–100
   calls have to come from a cloud API or a vLLM server (M7), not from this machine.
5. **Batching settings decide whether overload means "slow" or "dead".** With the server's
   defaults (8 prompts batched), 10 callers pushed GPU memory past 16 GB and the generation
   thread died; the process kept running and kept answering `GET /v1/models`, but every
   completion got a 404 until a restart. With 2 prompts batched the same load was slow but
   every call completed. For any self-hosted model server: cap concurrency below the memory
   limit, and health-check with a real tiny completion, never with a model list.
6. **The fallback path held under failure (D48).** Every one of the 640 failed turns ended
   with the polite "I'll pass your message to the owner" line, and every one is in the audit
   log as `model_unavailable`. No caller got silence and no wrong booking was made.
7. **Where the per-turn time goes at 1 caller** (from M3 plus this run): ~0.35 s prompt
   processing, ~0.4 s to the first token, then generation at 20–25 tokens/s for two model
   rounds (tool call, then the spoken answer), so 6–9 s. The fixes are: shorter answers,
   one model round per turn where possible, and streaming the first sentence to the voice
   layer (M5).

### Implications for the design

- Treat the Mac as a one-call development box. Gate 2 (friends) can run on it with calls
  taken one or two at a time; gate 3 needs the cloud model API from day one (D40).
- Add to the model adapter: a concurrency limit (semaphore) per model server, a tiny-completion
  health check, and automatic failover to the backup provider when the health check fails
  (D48). Without the limit, a burst of calls can take the server down for everyone.
- The load test runner stays as a tool: run it against the cloud API in M7 at 10/50/100.

## M3 — Prefix caching on the local model (2026-11-08)

**Question (D36, D37, D62):** does keeping the stable part of the prompt first and
identical in every request make the model server faster, and by how much?

**Setup:** Mac M5, 16 GB; `mlx_lm.server` 0.32.2 serving `mlx-community/Qwen3.5-9B-4bit`;
one request at a time; prompt ≈ 1,490–1,720 tokens (fixed instructions + Glow Salon
knowledge + calendar ≈ 1,440 tokens, then the conversation). A fixed 6-turn conversation
replayed for 3 calls per condition, `max_tokens=1` so the time measured is prompt
processing only, streaming on, token counts from the server's `usage`. Script:
`tools/measure_caching.py`; raw rows: `results/m3_caching.csv` (62 requests).

The three conditions differ only in the first characters of the system message:

| Condition | System message starts with | Cache reuse possible |
|---|---|---|
| **stable** (what we ship) | the normal prefix | across turns and across calls |
| **per-call** | `[call <id>] ` + prefix | across turns of one call only |
| **none** | `[<timestamp>] ` + prefix | none, like having no prefix caching |

### Prompt processing time per request

| Condition | Requests | Median prompt time | Slowest | Cached share | Uncached prompt tokens/s |
|---|---|---|---|---|---|
| stable | 18 | 0.35 s | 0.36 s | 97% | n/a (almost all cached) |
| per-call | 18 | 0.39 s | 3.31 s | 82% | 456 |
| none | 18 | 3.53 s | 3.89 s | 0% | 449 |

### First turn of a call (what a new caller waits for)

| Case | Prompt tokens | Cached | Prompt time |
|---|---|---|---|
| never-seen business, first request (cold) | 1491 | 0 | 3.50 s |
| same business, second request (warm) | 1491 | 1490 | 0.09 s |
| salon, call 1 (prefix cached since earlier calls) | 1486 | 1482 | 0.14 s |
| salon, call 2 | 1486 | 1436 | 0.35 s |
| salon, call 3 | 1486 | 1436 | 0.35 s |

### Interleaved calls to two businesses (salon, other, salon, other, …)

| Turn | Business | Prompt tokens | Cached | Prompt time |
|---|---|---|---|---|
| 1 | salon | 1486 | 0 | 3.55 s |
| 1 | other | 1478 | 0 | 3.58 s |
| 2 | salon | 1517 | 1482 | 0.32 s |
| 2 | other | 1509 | 1474 | 0.32 s |
| 3 | salon | 1558 | 1513 | 0.41 s |
| 3 | other | 1550 | 1505 | 0.41 s |

Generation speed on a warm prefix: 20–25 tokens/s; first token 0.4 s after the request.

### Findings

1. **The stable prefix makes prompt processing 10× faster:** 0.35 s against 3.53 s for the
   same conversation. This Mac processes uncached prompt text at about 450 tokens/s, so
   every request that cannot reuse the ~1,440-token prefix pays about 3.3 s before the
   first word. D36 is confirmed, and it is the single biggest speed lever found so far.
2. **Anything that changes at the start of the prompt costs the whole cache.** The
   "none" condition is what happens if a caller's name, the time, or a call id is put
   before the instructions. Nothing caller-specific may ever go into the system message.
3. **Reuse across calls matters as much as within a call.** With a per-call prefix the
   first turn of every call is cold (3.3 s); with the stable prefix a new call's first
   turn takes 0.14–0.35 s, because the previous call left the business prefix cached.
4. **The server keeps more than one prefix cached.** Alternating two businesses, both
   stayed cached (turn 2: 0.32 s each). But the cache is small: after 18 unique "none"
   prompts the salon prefix had been pushed out (interleaved turn 1: cold again). So
   cache-aware routing (D37) is about keeping each business's calls on a server that
   still holds its prefix, not about one business per server.
5. **Caching is a speed-up only, never a correctness risk:** cold requests gave the same
   token counts and the same answers; they were just slower. If a cache is lost, the
   server rebuilds it from the full request.
6. **Where the time goes now:** prompt processing on a warm prefix is 0.35 s, the first
   generated token comes at ~0.4 s, and generation runs at 20–25 tokens/s, so a 40-token
   reply takes ~2 s more. To reach the ~1 s goal (D60) the agent must speak short
   sentences and the voice layer must start speaking on the first sentence, not the last.
   The ~9 s turns seen in M2 were mostly generation plus a second model round after each
   tool call.

### Implications for the design

- Keep `prompt.py` as it is: fixed instructions → business knowledge → calendar →
  conversation. Add a test that fails if anything per-call sneaks into the system message
  (done: `tests/test_prompt.py::test_prefix_identical_across_turns_and_calls`).
- When the model moves to a cloud API (M7), check that the provider caches prefixes too and
  bills cached tokens cheaper; the cached share here (97%) is the number to compare.
- M4 (load test) should watch cached share under concurrent calls: if many simultaneous
  requests evict each other's prefixes, the "none" numbers above are what callers will feel.
