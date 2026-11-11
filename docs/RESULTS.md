# Results

Measured numbers, newest first. Each section says how it was measured so it can be re-run.

## Tamil and Telugu on the local model (2026-11-11)

How: `uv run python evals/run.py --k 2 --workers 2 --only south --out results/evals/<dir>`.
Same model as the main eval. Runs: `south-qwen3.5-9b` (first), `south-qwen3.5-9b-v2` (after
the time-of-day and repeated-call fixes), `south-promise-v3` (after the unbacked "I'll record
it" retry; promise personas only).

| Tamil / Telugu case | Run 1 | Run 2 (2 fixes) | Run 3 (3rd fix, promise only) |
|---|---|---|---|
| Pay now | 4/4 | 4/4 | |
| Promise to pay tomorrow | 1/4 | 1/4 | 4/4 |
| Stop messages | 3/4 | 2/4 | |
| Job loss, hand to a human | 0/4 | 2/4 | |
| Safety failures | 0 | 0 | 0 |

Run 1 pass^1 0.50, run 2 pass^1 0.56 (pass^2 0.25). 16 runs is a small sample; treat
differences of one or two runs as noise. Median turn is 21.7 s, slower than Hindi (15.5 s):
native-script replies use more tokens.

## Kisht eval — 160 simulated conversations on the local model (2026-11-10/11)

How: `uv run python evals/run.py --k 4 --workers 2 --out results/evals/local-qwen3.5-9b-v2`.
Agent and simulator both `mlx-community/Qwen3.5-9B-4bit` on `mlx_lm.server` (thinking off),
2 conversations at a time. Graded by code on the final ledger state plus safety checks.
Wall time about 3 hours. Errors 0. Median turn 15.5 s.

| Situation | Personas | pass^1 | pass^4 |
|---|---|---|---|
| Pay now | 3 | 1.00 | 1.00 |
| Adversarial (prompt injection, rudeness, "threaten me") | 5 | 0.95 | 0.80 |
| Opt-out | 2 | 0.88 | 0.50 |
| Negotiate (part payment, later date) | 6 | 0.71 | 0.33 |
| Hardship (job loss, illness, death) | 4 | 0.69 | 0.25 |
| Wrong person / identity | 3 | 0.67 | 0.67 |
| Promise to pay | 8 | 0.62 | 0.25 |
| Waiver / settlement / restructure | 3 | 0.42 | 0.00 |
| Dispute ("I already paid") | 2 | 0.38 | 0.00 |
| Questions about terms (RAG with citation) | 4 | 0.31 | 0.00 |
| **All** | **40** | **0.67** | **0.38** |

Baseline before D88 (`results/evals/baseline-v1-partial`, stopped at 124 runs): 48/124 passed (39%).
The same personas after D88: 80/128 (63%). Safety checks failed in 0 runs in both.

Failed checks (fixed run): escalate 21, promise 22, cites 9, followup 2, opt_out 1, link 1.
Guard blocks: false_claim_blocked 86, date_out_of_policy 14, leak_blocked 12,
banned_phrase 10, identity_mismatch 8, amount_out_of_policy 7, promise_exists 1, bad_followup_date 1.
Replies replaced: false_promise_claim 57, unbacked_link_claim 19, leak_before_identity 12,
false_claim 10, banned_phrase 10.

Notes: the simulator is the same 9B model, so some failures are the borrower's fault (it says
it is Priya, then says it is the neighbour; it ends the chat on turn 0). These are counted as
failures, not removed.

## M5 — Voice through Bolna (2026-11-08/09)

**Question (D25–D28, D60):** does the text brain work behind a real voice stack, and
where does the time go per turn?

**Setup:** the Bolna fork run from source (Python 3.12, no Docker) with `custom` LLM
provider pointing at our bridge (`receptionist bridge`, port 5050); speech-to-text Sarvam
`saarika:v2.5` (en-IN, VAD sensitivity off), text-to-speech Sarvam `bulbul:v3` ("shreya");
model Qwen3.5-9B on this Mac. Caller audio was produced by Sarvam's own TTS (a different
voice, "rahul") and streamed into Bolna's websocket by `tools/voice_probe.py` exactly as
the microphone client does (16 kHz PCM, 100 ms frames, mark acknowledgements). Reply time
= end of the caller's speech → first reply audio. Raw rows: `results/m5/voice_probe_*.json`.

### English caller, full booking by voice

| Caller said | Heard as | Reply after | Bridge time | Model calls | Reply audio | Outcome |
|---|---|---|---|---|---|---|
| "What are your timings on Sunday?" | exact | 2.9 s | 2.2 s | 1 | 6.0 s | answered from config |
| "…book a men's haircut tomorrow at eleven… Priya… 9845012345" (10.6 s line) | exact, one utterance | 13.4 s | 12.5 s | 3 (check + propose) | 8.2 s | read-back spoken |
| "Yes please, book it." | exact | **1.9 s** | 0.01 s | **0** | 10.1 s | **booked by code** |

### Hinglish caller

| Caller said | Heard as | Reply after | Outcome |
|---|---|---|---|
| "Kal subah gyarah baje men's haircut chahiye. Mera naam Priya hai, number 9845012345." | Devanagari: "कल सुबह 11 बजे मेंस हेयर कट चाहिए। मेरा नाम प्रिया…" | 7.0 s | model replied in Hindi, asked to confirm instead of proposing |
| "Haan, book kar do." | "Yes, book it." (translated by the STT) | 17.7 s | model then proposed; read-back spoken |
| "Facial ka kitna lagta hai?" | exact (Latin script) | 5.0 s | "Facial ki cost Rs 1200 hai…" |

### Hinglish caller, repeated (2026-11-09, same three lines, four voice runs + text)

The question was whether the Devanagari first turn makes the model call the tools.

| Where | First turn called check_availability | Read-back reached by turn 2 | Notes |
|---|---|---|---|
| Text, straight to the model (5 lines: 2 Devanagari, 2 Hinglish, 1 English) | 4/4 lines that named a time (the 5th rightly asked for a time) | — | one Devanagari line was answered in English |
| Voice through Bolna, 4 runs | 2/4 | 3/4 | reply after 6–16 s on turn 1 |

So the tools are called; what varies is *when*. Three things found and fixed on the way:

1. One run used all three tool rounds (`check` → `check` with the wrong staff → `book_visit`)
   and the caller heard "Sorry, I couldn't sort that out" even though the proposal had
   succeeded. The session now speaks the read-back itself when the last round proposed.
2. The read-back and the "Done, it's booked" summary were English for every caller. They now
   follow the call's language ("…Ravi ke saath, Tuesday 10 November ko 11:00 AM baje… Book
   kar doon?").
3. A caller whose transcript is pure Devanagari was not detected as Hindi (the detector
   only knew Latin-script words), so even the fixed lines came out in English. Fixed.

Still varying, not fixed: after `check_availability` the model usually asks its own "shall
I book?" instead of calling `book_visit` at once (one extra turn, D73 known gap), and the
first-turn reply is sometimes English for a Devanagari caller. Both are model behaviour; the
M6 eval suite (D65) will count them, and the cloud model (D40) is expected to do better.

### Where a turn's time goes (from the three runs)

| Step | Time |
|---|---|
| End of speech → final transcript (Sarvam, VAD off) | ≈ 0.4–0.7 s |
| Bridge: model + tools (this Mac) | 2–6 s for a plain answer; 12–17 s when a turn needs two tool rounds |
| Reply ready → first audio heard (Sarvam TTS first chunk) | ≈ 0.7–0.9 s |
| Caller's "yes" → "Done, it's booked" | 1.9 s, no model call at all (D70) |

### What broke on the way, and the fix

1. Deepgram key rejected (401 everywhere) → switched both speech directions to Sarvam.
2. Bolna only plays a welcome from pre-rendered audio and the hosted platform renders it;
   locally the welcome never played, and a web call also crashed in `handle_init_event`
   without context data, which stopped the welcome from starting at all → every transcript
   was dropped as "welcome still playing". Fixed in the fork (quickstart renders the
   welcome once per agent with Sarvam; init guard; `set_stream_sid` on the mic handler).
3. The mic client and probe never acknowledged `mark` events, so Bolna never learned the
   welcome had been heard → both now acknowledge.
4. Sarvam's VAD (high sensitivity by default) chopped a dictated phone number into six
   turns; `optimize_latency` additionally sent every *interim* transcript to the model.
   Fixed: `high_vad_sensitivity: false` (added to Bolna's config schema), `incremental_delay`
   1.5 s, `optimize_latency: false`. The 10.6-second booking line then arrived as one
   utterance with the full number.
5. The bridge now runs one turn at a time per call, skips turns Bolna has already
   cancelled, and drops replies the caller never heard (keeps the notebook equal to what
   was said and heard, D33).
6. Hindi speech comes back in Devanagari: yes/no detection now understands it.

### Still open after M5

- The real microphone test by a person and the Twilio call (tunnels need to be opened by
  hand; see RUNBOOK notes in the commit).
- Hinglish: tools are called on the first turn in about half the voice runs (see the table
  above); `saaras:v4` (keyterms, better code-mixing) and a Hinglish example in the prompt
  are the next things to try, counted by the M6 eval suite.
- Turn time is dominated by the local model (D76); the voice layer adds about 1.5 s.

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
