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
- D102. Supervisor controls: a private note to the AI ("coach") and a take-over. Both are guard methods, so they are audited, and both travel through the shared call state, so a dashboard supervisor can reach a call running in another process. A note is added to the model's next request only; the reply still passes every check, so a supervisor cannot talk the agent past a rule. After a take-over the model is not called again: code says the hand-over line.
- D103. Identity answers are masked. The borrower's turn that carries a date of birth or PIN code has its digits masked before it is written to the call log, and `verify_identity` arguments are masked in the audit trail. The live call state (Redis, expiring) keeps the real words because the model needs them.
- D104. A human can mark the QA scorecard on any call. Human marks are stored beside the AI reviewer's and never replace them, so agreement between the two can be measured (an LLM judge is only useful once you know how often it is right). The code-checked item is left out of the agreement number.
- D105. The human desk works to a deadline per kind of case (`desk_sla_hours` in the lender YAML). When a case is resolved, the resolution is written to the borrower's case notes as a `desk` contact, which the agent reads after identity next time. A desk note does not count as a contact attempt.
- D106. Containment (reached borrowers the AI handled without a human) and a per-language table are on the overview: the per-language table is where a weaker language shows first.
- D107. Reply time on the local model is mostly writing time (about 25 tokens a second), so: replies are capped by instruction at one or two short sentences; a successful identity check returns the dues itself (one model round less); the model is told to check identity before its first try when the borrower's words contain a birth year or PIN; and the model server reads the instructions while the greeting plays. Measured on one Hindi chat: 4-12 s per turn before, 2-5 s after; first reply 6-8 s before, 1.4 s after.
- D108. On a voice call the borrower hears the start of a reply while the rest is still being written. Measured: the model starts writing after 0.1-0.5 s but needs 2-3 s for a whole reply, and the bridge used to wait for the last word. Rules: (a) a sentence goes out early only if the reply so far is plain talk (no number, and no word about an action such as record, promise, link, send, verify, in any of the four languages) and passes every reply check; from the first sentence that is not, everything waits for the whole reply, as before. Reason, seen live in Tamil: the model wrote "your promise is recorded" just before the tool call that refused it, and until a reply ends code cannot know whether a tool call follows. (b) On a tool turn code first says a short "one moment" line; it is logged but kept out of the transcript so the model does not learn to say it. (c) If the rest of a reply is blocked after a clean start, the safe line follows. (d) A call is prepared while it rings (`POST /prepare` on the bridge, also done by `tools/make_voice_agent.py`): the model server reads that borrower's instructions and greeting. Tried and rejected: moving the borrower's name out of the system message so that every call shares one cached copy (every call started warm, but first replies got worse: about 1 in 4 odd against 1 in 32, same 8 borrowers side by side); and stopping the model as soon as a reply will be asked again anyway (the cut sometimes removed the tool call that follows the words). Measured through the bridge on Hindi calls with the local model: first words after 1.1-2.4 s on talk and identity turns (whole reply 1.7-6.6 s); first reply of a prepared call 1.1-1.4 s instead of 5-9 s.
- D109. Guard gaps found while testing D108, now closed: before identity is verified the agent may not offer a date of birth or PIN itself (it asked "is your date of birth 1990-05-15?", invented; rule `guessed_identity`, replaced by the ask-for-identity line); passive forms of "the promise is recorded" in Hindi, Tamil, Telugu and English count as that claim; a promise claim with no tool call and no promise waiting gets one retry before it is blocked. The agent's reply length is capped at 200 tokens (was 400).
- D110. Hardening before the first real phone call, from an independent read of the code (19 findings; the ones that could hurt a live call are fixed, the rest are listed in the README under limits). (a) A voice run id is bound to its borrower and to an open call: unpatched Bolna sends no run id, so the next borrower continued the previous borrower's verified conversation. (b) Any failure inside a voice turn (Redis, a locked database, a bug) is spoken as the fallback line and logged; before, only a model failure was, and everything else was a silent 500. Redis has socket timeouts. (c) While someone is waiting on a call the model gets `live_call` limits (20 s per request, 5 s in the queue, no retry) instead of the batch limits (120 s, 300 s, one retry). (d) Background work (reviews, the planner, case notes of quiet calls) can never hold the model server's last slot. (e) `KISHT_BRIDGE_TOKEN`, if set, is required as a bearer token on the bridge (Bolna sends it as its LLM key); Docker publishes both ports on 127.0.0.1 only. (f) The bridge's `/health` is cheap by default and runs a real completion only with `?deep=1`. (g) A caller who speaks over the agent stops the model call in flight. (h) The dashboard's test chat is rebuilt from shared state per request with one turn at a time per chat; `/api/live` no longer closes a quiet chat before the sweeper can wrap it up; a stopped model server is a 503 with a plain message. (i) Ledger in WAL mode, indexes for the queries that run, logging switched on, audit kept in memory only as a recent tail. Not done: a login for the dashboard (it stays a local tool), one shared model-slot limit across processes, and grouping the dashboard's per-call queries (measured: every endpoint answers in under 35 ms at today's size).
- D111. Each recovery-conduct rule is traced to the code that enforces it. `compliance/rbi-recovery-2027.yaml` has one row per rule of RBI's 2026 recovery directions for NBFCs (RBI/2026-27/230, in force from 1 January 2027), plus the 2022 circular and the digital lending directions where they add something: paragraph, what it requires (paraphrased), status, the guard, the tests, the block codes. Tests fail if a row points at something that does not exist or if `docs/COMPLIANCE.md` is out of date, and the dashboard's Rules page shows how often each rule stopped something. Honest by design: "partly" rows must say what is missing, gaps are listed, and Kisht's own numbers (attempt caps, promise limits) are marked as its policy, not the regulator's. Three gaps the rules exposed are closed: no agent contact while the human desk has an open hardship, bereavement or dispute case (100Y(6)); a phone call's greeting says it is recorded (100P); the payment-link message and any answer about complaints carry the grievance officer's details (100AA). The directions do not mention automated or AI callers; the rules for a human agent are applied to the AI. The rule text was read through a summarising reader, so paragraph numbers were cross-checked between the bank and NBFC versions but quotes were not checked character by character.
- D112. The agent's known weakness is a published number, and the guard is measured against it. `kisht claims` counts, per language, how often the model claims an action it did not take, where code stopped it (asked again, replaced) and how many reached the borrower, and splits the pass rate into runs that passed cleanly, runs that passed because code caught a false claim, and runs that passed although one was heard. Over 176 simulated conversations: 16.8 per 100 agent turns, 149 of 168 stopped, pass rate 65.9% of which only 33.0% clean. Measuring it found three guard faults, all fixed: a Tamil pattern that took "registered mobile number" for "promise recorded" (added one day earlier), a Telugu pattern with an optional verb that took a Hindi apology for a waiver (old), and two claim wordings no pattern knew ("your payment has gone through", "I am recording it now"). The detector is pattern-based and says so; its misses were sized by reading unflagged replies by hand (7 in 38).
- D113. Demo shortcuts are refused unless the config says so, and four rules stop depending on luck. From three independent reads of the code against one question: what stops this running for a real lender. (a) `mode: demo` in the config allows a fixed clock (`--at`, which also switches off the calling window and the attempt caps), `simulate`, the made-up loan book, a voice bridge with no token and a dashboard reachable from another machine. A config without that line is production and refuses all five; the shipped configs say demo. A lost data volume now stops the container instead of quietly serving made-up borrowers. (b) The attempt caps are counted and the attempt is logged in one transaction: before, two workers could both pass a cap with one attempt left. (c) The desk's "resolved" updates the ledger row the guard reads; before, it only updated the dashboard's own table, so a resolved hardship case blocked agent contact for ever (the rules table claimed otherwise). (d) A clear, lasting request to stop ("stop calling me", "dobara call mat karna") is recorded by code with a fixed reply and no model call; "not now" and "not at work" do not match and stay with the model. The Tamil and Telugu patterns were not checked by a native speaker. (e) A reply the caller never heard takes its promise read-back with it, so a later "haan" cannot save a promise nobody read out. Not done here, next stages: a login for the dashboard, a pre-dial check that counts unanswered calls, tools that still run after the caller cuts in, Postgres, a real payment link and SMS.
- D114. The agent no longer says a safe line where it can do the thing, and the eval now sees the conversation, not only the ledger. (a) When the model says "I have sent the link" or "I have passed this to our team" and, after one more try, still has not called the tool, code does it through the same guard and then says a sentence built from the result (a link for what is due; a hand-over, to the hardship team if hardship was mentioned, otherwise as a call-back case). Before, the borrower got "shall I ask our team to call you?", in one passing eval run five turns running. Not done by code: a promise (it needs an amount and a date) and an opt-out claimed by the model (only the borrower's own words opt them out, D113). (b) The offer of a team call is made once: a clear yes to it opens the case with no model call, and if the agent would have to offer it twice in a row, code opens the case instead. (c) Where the model server accepts it (`force_tool_on_retry` on a role, off by default), the second try names the tool the model must call. (d) On a call, no tool runs for a turn the caller has already talked over. (e) Each eval run also gets quality checks that do not change `passed`: at most one reply replaced by code, no reply in a different language from the borrower's message, no repeated reply, not cut off by the turn limit. A run is clean only if it passed and all four hold. Re-scoring the published 160 runs: 66.9% passed, 95% interval 56% to 77% (whole personas resampled), and 38.1% clean; 47 runs hit the turn limit, 23 had a wrong-language reply, 22 had two or more replaced replies, 21 a repeated reply. Differences under about ten points between two runs of this size mean nothing. (f) The model's blocked words are kept in each eval row, so a guard that blocks a harmless sentence can be counted. (g) `evals/personas_heldout.yaml`: 20 personas written by a separate reader that was not allowed to open the prompt, the cue lists or the claim patterns; never to be used for tuning. `--smoke` runs 8 personas, one per kind, and `--min-pass` makes the run fail below a pass rate, for a CI gate once a hosted model is configured. First full run with (a) to (d) (`local-qwen3.5-9b-v6`, 160 runs): 56% passed (interval 45% to 66%), 33% clean, against 67% and 38% before. Three causes, read from the transcripts, and their fixes: (h) "I have paid" answered by the model with "your payment is complete" became a team call-back; now code says it cannot see the payment yet (fixed before the run). (i) A blocked "your promise is recorded" led to the team offer and then a call-back, which sent 16 borrowers who only wanted to name a date to the human desk; now code first asks "which date, and how much?" and offers the team only if that was already the last thing said. (j) Code sent a link when the model said "sending the link for the 14th" (13 runs: link sent, promise never recorded); now a link claim right after the borrower names a day gets the same question instead of a link. (k) Hardship: the model kept bargaining and never handed over (hardship pass rate 31%); now a borrower in hardship is never sent a link or asked for a date by code, and after two model replies with no hand-over, no promise waiting and none saved, code hands the case to the hardship desk. The Hindi hardship cue missed "job chhodne" and "kaam chhod diya". The claims report counted code's own "I have recorded that, we will not call you again" as a false promise; it no longer does when the opt-out is in the same turn. The held-out set scored 62% (interval 47% to 78%), 42% clean, on the same build; its transcripts were not read.

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
