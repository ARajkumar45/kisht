# Decisions — Kisht

One line per decision. To change one: edit its line, add the date and the reason.

This repository began as a phone receptionist for small businesses (milestones M1 to M5). The
decisions from that phase are kept below, numbered D1 to D87, because Kisht reuses what they
built: the voice path, prompt caching, concurrency limits and the "code confirms, the model
never does" pattern. Decisions made for Kisht itself come first.

## Kisht: EMI repayment agent and contact centre
- Design rule: the model plans and decides; code guards only what must never go wrong (calling hours, threats, account details before identity, money changes without a human), and every guard decision is audited.
- Local first: the default run is entirely on one laptop; every outside piece (model per role, speech, channel, store, lender policy, language) sits behind a small interface chosen in config.
- Synthetic borrowers only. Nobody real is ever contacted.
- D88. A borrower confirms a promise by repeating it ("haan, kal 11 November ko 3000"). The yes-check drops words that agree with the pending promise (its amount, day, month, weekday, kal/aaj/parso by offset) and then applies the strict salon-era check, so a different amount or date is still a change. Found by error analysis of the first eval run: promise personas went from almost all failing to 62% pass^1.
- D89. Opt-out, escalation and agreement questions never need identity; the prompt says so explicitly because "identity first" made the model ask for a DOB before honouring "stop messaging me". A claim of payment the ledger does not show is a dispute: escalate, never argue or send a link.
- D90. Eval result on the local 9B model: pass^1 0.67, pass^4 0.38, zero safety failures in 160 runs. The model's weak spots are escalation and tool use for agreement questions; the next lever is a bigger model through the same adapter, not more prompt rules.
- D91. Language is a plug-in: one module per language (kisht/languages/<code>.py) holds every language-specific line, word list and phrase. Code checks use English plus the call's language, not every language at once, so a Hindi word cannot be misread as a Tamil "no". Tamil and Telugu speech goes to Sarvam STT with ta-IN / te-IN; Hindi keeps en-IN (D84). Code lines are in native script so text-to-speech reads them correctly; on a voice call the model is told to reply in native script too.
- D92. The 40 Tamil/Telugu borrowers in the loan book use their own random stream, so the original 200 (and every demo and doc that names them) stay identical.
- D93. Three fixes found by the Tamil/Telugu runs, all general: time-of-day words do not block a yes to a date-only promise; identical tool calls repeated within one turn stop the loop (code reads back a pending promise instead); "I'll record it" without the tool counts as a stall and gets one retry. Promise personas went from 1/4 to 4/4.
- D94. Contact-centre data lives in its own store (insights.sqlite), not the ledger: the ledger is the lender's book of money and promises; the call log, traces, reviews and desk state are the contact centre's. Both are written as things happen, so live views need no extra plumbing.
- D95. Tracing uses OpenTelemetry with GenAI attribute names, exported to our own store for the dashboard and optionally over OTLP. All turns of a call share a trace id derived from the call id, so a conversation is one trace even across separate voice requests. Borrower text stays out of span attributes (it is in the turn log); spans carry timings, tokens, tool names and guard outcomes.
- D96. Post-call QA: the model judges what needs judgement on the lender's scorecard; anything code knows for sure is filled in by code (identity before details is enforced by the guard, so it cannot fail), and compliance counts come from the guard's blocks, never from the model.
- D97. Dashboard in React + TypeScript with no chart library (CSS bars), built by Vite and served by the same FastAPI process; Docker builds it in a Node stage.
- D98. A conversation is wrapped up the same way whoever ended it: case note, ledger contact closed, post-call review. Chats end on "End"; a voice call just goes quiet, so a sweeper finishes live calls that have been silent (voice 5 minutes, chat 30) and a Redis lock makes sure two processes never wrap up the same call. On the voice path the wrap-up runs in the background so the caller hears the last reply at once.
- D99. The reviewer model is given the facts code recorded (identity verified or not and in which turn, tools used, promise saved, link sent, what was blocked) and told not to contradict them. Found when a review said "failed to verify identity" on a call where identity was verified. Its remaining judgement calls are still unmeasured against human labels; that is the next quality step.
- D100. Dates reach the model in words with the weekday (get_dues.dates_in_words). The model must never work out a weekday itself: it called a Saturday "Sunday" in Tamil.
- D101. A call's audit trail is read from the audit files on disk, because each process (chat, voice bridge, simulator, dashboard) writes its own file.

# Earlier phase: phone receptionist (M1 to M5), kept for the record

## Product
- D1. Product: an AI phone receptionist for small businesses in Bengaluru, India.
- D2. Problem: missed calls turn into lost bookings.
- D3. Channel: phone calls only, overflow only — the agent answers calls staff miss, through call forwarding.
- D4. WhatsApp: later, not now.
- D5. Demo channel *(kept, adapted)*: a browser "talk to the agent" link, for recruiters and demos only, not a product channel.
- D6. First customer: not named yet; friends are finding a contact.
- D7. Preferred customer type: an appointment-based business (clinic, salon, or PG room visits).
- D8. Business as a template: each business is one config file, so the business can be swapped without code changes.
- D9. Builder: I build and run this alone.
- D10. Quality bar: production-grade, able to handle many calls at once, sellable to more businesses later.

## Languages
- D11. Languages are decided by who calls the business; design for multiple languages from the start.
- D12. Likely languages: English, Hindi, Kannada; Telugu and Tamil as options.
- D13. Rollout *(kept)*: English and Hindi (with Hinglish mixing) working first; Kannada next (needs Sarvam speech-to-text, as Deepgram's Kannada is weak), when they pass or the first customer needs it.

## Budget
- D14. Build on free and trial options first.
- D15. Model while building: local Qwen3.5-9B (4-bit) on my Mac via `mlx_lm.server` (OpenAI-compatible, port 8080).
- D16. Most testing through a text simulator and microphone chat, not paid phone calls.
- D17. Speech: existing Deepgram credit.
- D18. Real test calls: Twilio trial, a few calls only.
- D19. Host while building: my Mac.
- D20. Gate 1, demo works: ₹0.
- D21. Gate 2, friends test by phone: small top-up plus a rented number.
- D22. Gate 3, real business pilot: cheap cloud server plus credit, capped at ₹3,000/month, alert at 80%.
- D23. Track cost per minute from the first call.
- D24. Every paid part is swappable for a cheaper one (e.g. Exotel/Plivo for Indian numbers, Sarvam for Indian-language speech).

## Voice engine
- D25. Voice engine: open-source Bolna, self-hosted from ~/Documents/mac/bolna_project (not the paid hosted Bolna platform).
- D26. Bolna handles the phone audio stream, speech-to-text, the model call, text-to-speech and interruptions.
- D27. Load-test Bolna before trusting it at scale.
- D28. Fallbacks if Bolna hits limits: Pipecat or LiveKit Agents.

## Architecture
- D29. Telephony provider receives the call and streams audio to us.
- D30. A load balancer spreads new calls across call workers and keeps each call on the same worker for the whole call.
- D31. One agent session per call; a session is the call's notebook, the business instructions and its tools — never a copy of the model.
- D32. Call workers are stateless, scale horizontally, and autoscale on number of active calls.
- D33. Redis holds each call's notebook and state (source of truth for the conversation) plus per-business config for fast reads.
- D34. One shared, stateless model service for all sessions; each turn sends the call's notebook.
- D35. The model server uses continuous batching; we never start one model copy per call; add replicas when a server is full.
- D36. Prefix caching: stable part first and identical in every request (instructions + business knowledge), then the conversation.
- D37. Cache-aware routing: all turns of one call go to the same model server; an evicted cache is rebuilt from the notebook.
- D38. Model routing: simple turns to a small fast model; hard turns to a bigger model or the human owner.
- D39. Start with one agent plus routing; split into specialist subagents only if tests show a need; context travels with any handoff.
- D40. Model backends switchable by config: local mlx (building, demos), cloud model API (first pilot), self-hosted vLLM on a rented GPU (later, at volume).
- D41. Later: compare cloud API vs vLLM on cost per call and reply time at 10, 50 and 100 calls.
- D42. Business rules enforced in code, never only in the prompt.
- D43. No booking or change without the caller's explicit yes.
- D44. Read the booking back before saving it *(kept)*.
- D45. Never promise what the owner must confirm.
- D46. Audit log of every tool call and decision.
- D47. Human handoff: when unsure, offer to connect the caller to the owner or take a message.
- D48. Fallbacks: respect outside rate limits, retry briefly, switch to a backup provider; if all fail, play a polite message and pass the call to the owner.
- D49. Message queue plus background workers for slow work (transcripts, owner summary, dashboard); the live call never waits on slow work.
- D50. Postgres for permanent records: businesses and config, calls, bookings, audit log.
- D51. Monitoring dashboard: active calls, reply time, errors, cost per call, with alerts.
- D52. Multi-tenant: the number that was called decides which business config loads.
- D53. Emergency check *(kept, for clinic configs)*: a fixed keyword-and-rule check runs every turn, outside the model; on a match, give the 108/112 script and alert the owner. Clinic agents never give medical advice.

## Privacy
- D54. Follow India's DPDP Act 2023.
- D55. Tell callers the call is handled by an assistant and may be recorded.
- D56. Store personal data safely; delete it on request.
- D57. Delete recordings and transcripts after 30 days; keep bookings *(kept)*.
- D58. Check the exact legal requirements before the pilot.

## Success measures (recorded, not assumed)
- D59. Share of missed calls answered without the owner; bookings captured; mistakes.
- D60. Reply time per turn; goal about 1 second; measured.
- D61. Load tests at 10, then 50, then 100 simulated concurrent calls, with reply time and errors at each level.
- D62. Cached tokens and reply time with and without the stable prefix.
- D63. Cost per minute and per call.
- D64. Test pass bar *(kept)*: a milestone is done when ≥ 90% of scripted test calls are correct and there are zero dangerous failures.
- D65. Every mistake found in a call becomes a new scripted test call *(kept)*.
- D66. Expected finding: one Mac's model server will not really serve 50–100 calls at once; Mac load tests show its limit; real numbers at that scale come from the cloud API or vLLM.

## Way of working
- D67. One milestone at a time; never build ahead.
- D68. No dates; move to the next milestone when the current one's exit criteria are met *(kept)*.
- D69. Python pinned to 3.12 with `uv`, since the system Python 3.15 is too new for many voice libraries *(kept)*.

## Learned while building M2 (2026-11-08)
- D70. The model has no tool to confirm a booking. `book_visit` only proposes and returns the read-back; when the caller's own words are a clear yes, session code books it and answers, with no model call. (Replaces the two-step `confirm=true` tool from the M2 plan: Qwen3.5-9B never used it correctly, and it gave the model a way to try booking on its own.)
- D71. A caller reply that names a time, a number or a day ("Theek hai, 12 baje kar do") is never a clear yes: it is a change request. Found live: it booked 11:00 when the caller asked for 12:00.
- D72. No "keep replies to one or two sentences" rule in the prompt: with Qwen3.5-9B it stopped tool calls (0/12 with it, 10/12 without). Opening hours, prices and other config facts may be stated without a tool; anything about free times must come from `check_availability`, enforced in code with one retry.
- D73. Thinking mode stays off for the local model: 12/12 tool calls vs 11/12, but 22 s a turn vs 9 s.
- Known gap (for the test suite, D65): the model often asks its own "shall I book?" after `check_availability` instead of calling `book_visit` at once, costing the caller one extra turn. Safe, but slow.

## Learned in M3 (2026-11-08, see docs/RESULTS.md)
- D74. The stable prefix is confirmed worth it: prompt processing 0.35 s with it, 3.5 s without (10×) on the local server. Nothing caller-specific ever goes before the conversation in a request.
- D75. The local server keeps a small number of cached prefixes, not one: cache-aware routing (D37) means keeping a business's calls on a server that still holds its prefix.
- D76. Latency target (D60) needs short spoken sentences and sentence-by-sentence voice streaming: on this Mac the model generates 20–25 tokens/s, so reply length, not prompt processing, now dominates turn time.

## Learned in M4 (2026-11-08, see docs/RESULTS.md)
- D77. Our call-worker layer is not the bottleneck: 100 simultaneous callers with an instant model all booked in 0.5 s with no errors (~20,000 turns/min on one process). The model server is the limit.
- D78. SQLite connections are per thread (a shared one failed 9 of 10 concurrent callers); the write lock plus a 32-thread race test guarantee one booking per slot.
- D79. This Mac handles 1–2 simultaneous calls; at 5 turns double, at 10 they reach ~37 s, and with default batching 10 callers crash the GPU out of memory and the server stays dead (404) until restarted. Gate 2 runs on the Mac with 1–2 calls at a time; gate 3 uses the cloud model API (D40) from day one.
- D80. The model adapter must get a per-server concurrency limit, a health check that sends a tiny completion (listing models stays "healthy" while completions fail), and failover to the backup provider when it fails (D48). To be built before any phone traffic (M5/M6).

## Learned in M5 (2026-11-09, see docs/RESULTS.md)
- D81. Speech-to-text and text-to-speech are Sarvam (`saarika:v2.5` en-IN, `bulbul:v3`), not Deepgram: the Deepgram key never authenticated, and Sarvam handles Hindi/Hinglish natively. Still swappable per D30 (one block in the agent config).
- D82. Sarvam's voice-activity detection runs with `high_vad_sensitivity: false`, `incremental_delay` 1.5 s and `optimize_latency: false`: with the defaults a dictated phone number arrived as six turns and interim transcripts reached the model. Cost: ~0.5 s more before the turn ends; worth it for whole utterances.
- D83. One turn at a time per call in the bridge: a turn Bolna cancelled (caller spoke again) is skipped, and a reply the caller never heard is removed from the notebook, so the notebook equals what was said and heard (D33).
- D84. Sarvam returns Hindi speech in Devanagari even in en-IN mode, and sometimes translates Hinglish to English. Every code-side word check (yes/no, times, days) must understand Devanagari as well as Latin spellings.
- D85. Bolna's welcome message must be rendered to audio locally (the hosted platform did it for them); the fork does this once per agent with Sarvam. Four fork patches were needed for local web/mic calls (welcome, init guard, stream id, mark acknowledgements); keep them as separate commits so they can be sent upstream.
- D86. Measured per turn: speech end → transcript ≈ 0.5 s, reply → first audio ≈ 0.8 s, so the voice layer adds ≈ 1.5 s; the local model adds 2–17 s (D76, D79). The caller's "yes" is answered in 1.9 s with no model call (D70). The 3 s target (D60) needs the cloud model API, not more voice tuning.
- D87. Everything the caller hears from code (read-back, booked line, fallbacks) follows the call's language, and a Devanagari transcript counts as Hindi. If a `book_visit` succeeds in the last allowed tool round, the session speaks the read-back itself instead of giving up.
- Known gap: on a Devanagari first turn the model calls the tools in about half the voice runs (4/4 in text) and often asks its own "shall I book?" after `check_availability`; `saaras:v4` and a Hinglish prompt example are the next things to try, counted by the M6 eval suite (D65).

## Open questions (from the receptionist phase)
- O1. Which business is the first customer (clinic, salon, or PG)?
- O2. Which languages do that business's callers actually use?
- O3. Which cloud model API for the pilot, and which cloud server and region?
- O4. Exact DPDP Act requirements (notice wording, consent, retention, processors) — check before the pilot.
- O5. Indian number for the pilot: Exotel or Plivo, and whose KYC?
- O6. Does Bolna hold up under load, or do we switch to Pipecat / LiveKit Agents?
- O7. Rest of "How to work with me" and the "Engineering rules": the brief was cut off; needed to finish CLAUDE.md.
- O8. Public GitHub repo after gate 1? (Was decided yes before the rewrite; reconfirm.)
