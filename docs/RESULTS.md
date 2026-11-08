# Results

Measured numbers, newest first. Each section says how it was measured so it can be re-run.

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
