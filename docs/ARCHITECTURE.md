# Architecture — AI Receptionist

Plain-English design of the system. Decision numbers (D1…D69) point to `docs/DECISIONS.md`.
This file replaces the earlier `docs/PLAN.md` (kept in git history).

---

## 1. What it does, in one paragraph

A small business in Bengaluru forwards the calls its staff miss to our number (D3). Our
agent picks up, says it is an assistant and the call may be recorded (D55), answers
questions from that business's config, and books visits — but only after reading the
booking back and hearing the caller say yes (D43, D44). When it is unsure, it offers to
connect the caller to the owner or takes a message (D47). The owner gets a summary of
every call. Many calls can run at the same time, for many businesses (D10, D52).

## 2. The big picture

```
 Caller ──► Business number ──(missed call forwarded)──► Telephony provider
                                                         (Twilio now; Exotel/Plivo later)
                                                                 │ audio stream
                                                                 ▼
                                                        ┌─────────────────┐
                                                        │  Load balancer  │  sticky: one call
                                                        └────────┬────────┘  stays on one worker
                                     ┌───────────────────────────┼───────────────────────────┐
                                     ▼                           ▼                           ▼
                              ┌─────────────┐             ┌─────────────┐             ┌─────────────┐
                              │ Call worker │             │ Call worker │    ...      │ Call worker │
                              │ (Bolna)     │             │ (Bolna)     │             │ (Bolna)     │
                              │ session A   │             │ session C   │             │ session E   │
                              │ session B   │             │ session D   │             │             │
                              └──┬───┬───┬──┘             └─────────────┘             └─────────────┘
                                 │   │   │
           speech-to-text ◄──────┘   │   └──────► text-to-speech
           (Deepgram / Sarvam)       │            (Deepgram / Sarvam)
                                     │
            ┌────────────────────────┼──────────────────────────────┐
            ▼                        ▼                              ▼
     ┌─────────────┐        ┌────────────────┐             ┌─────────────────┐
     │   Redis     │        │ Model router   │             │ Tools + Guard   │
     │ notebooks,  │        │ small / big /  │             │ (business rules │
     │ call state, │        │ owner          │             │  in code)       │
     │ biz config  │        └───────┬────────┘             └───────┬─────────┘
     └─────────────┘                ▼                              ▼
                           ┌──────────────────┐            ┌──────────────┐
                           │ Model service    │            │ Postgres     │
                           │ (shared, batched,│            │ businesses,  │
                           │  prefix-cached)  │            │ calls,       │
                           │ mlx / cloud API /│            │ bookings,    │
                           │ vLLM replicas    │            │ audit log    │
                           └──────────────────┘            └──────────────┘
                                                                  ▲
           Message queue ──► Background workers ──────────────────┘
           (transcripts, owner summary, dashboard updates)        │
                                                                  ▼
                                                       Monitoring dashboard + alerts
```

## 3. The parts, one by one

### 3.1 Telephony provider (D29)
Receives the forwarded call and streams the caller's audio to us over a websocket.
Twilio while building (trial, D18). Exotel or Plivo later for Indian numbers (D24). It
sits behind a small adapter so swapping provider is a config change.

### 3.2 Load balancer (D30)
Spreads **new** calls across call workers. Once a call lands on a worker, every audio
packet of that call keeps going to the same worker ("sticky"), because the live audio
stream can't jump between machines mid-call.

### 3.3 Call workers and sessions (D31, D32)
- A call worker is a process running Bolna (D25). It runs many calls in parallel.
- Each call gets one **session**. A session is small: the call's **notebook** (the
  conversation so far), the business's instructions, and its tools. It is **not** a copy
  of the model.
- Workers keep nothing important in memory — the notebook lives in Redis. So a worker can
  be added or removed at any time. We add workers when the number of active calls grows.

### 3.4 Bolna's job (D26–D28)
Bolna handles the hard real-time part: the audio stream, turn-taking, speech-to-text,
calling the model, text-to-speech, and the caller interrupting the agent. Our code plugs in
as the "brain" behind it: the session, the tools, the guard. We load-test Bolna before
trusting it. If it hits limits, Pipecat or LiveKit Agents can replace it, and because our
brain is separate, only the voice layer changes.

### 3.5 Redis (D33)
Fast shared memory for live calls:
- `call:{id}:notebook` — every turn, in order. **This is the source of truth for the
  conversation.**
- `call:{id}:state` — language, stuck counter, pending booking waiting for a yes, which
  model server this call is pinned to.
- `biz:{id}:config` — the business config, cached for fast reads.

Records expire after the call ends; anything permanent goes to Postgres via the queue.

### 3.6 Shared model service (D34, D35)
- All sessions send their requests to the same model service. The model **remembers
  nothing** between requests; each turn we send the call's notebook.
- The server uses **continuous batching**: in one step it works on many calls' requests
  together, reading the model weights once for all of them. That is why one server can
  serve many calls, and why we never start one model per call.
- When one server is full, we add another copy (a replica).
- On the Mac, `mlx_lm.server` serves one model; how well it batches is something we
  measure, not assume. We expect the Mac to top out well below 50–100 calls (D66).

### 3.7 Prefix caching (D36, D37)
Every model request is built in the same order:

```
[ fixed system instructions ]   ← identical for every call
[ business knowledge from config ] ← identical for every call to this business
[ the call's notebook ]         ← changes every turn
```

The model server can remember the work it already did on the first two parts and skip
it next time. That makes replies faster and cheaper.
- **Cache-aware routing:** all turns of one call go to the same model server, so its
  cache is found there.
- **If a cache is thrown away:** the server just rebuilds it from the full request. Answers
  stay correct; caching only adds speed and lowers cost.
- We measure cached tokens and reply time with and without the stable prefix (D62).

### 3.8 Model routing (D38, D39)
A small, cheap check decides where each turn goes:
- **Simple turns** (timings, prices, FAQs) → small fast model.
- **Hard turns** (confused caller, complaint, heavy language mixing) → bigger model.
- **Beyond the agent** → the human owner (handoff).

Start with **one agent plus routing**. Split into specialist agents (FAQ, booking,
escalation) only if tests prove it helps — every handoff between agents adds delay. If we
ever split, the full notebook travels with the handoff.

### 3.9 Model backends (D40, D41)
One client that talks to any OpenAI-compatible server, chosen by config:
1. **Local mlx** on the Mac (`http://localhost:8080`, Qwen3.5-9B 4-bit) — building and demos.
2. **Cloud model API** — first pilot; scales from day one.
3. **Self-hosted vLLM on a rented GPU** — later, to save money at volume.

Later we compare 2 vs 3 on cost per call and reply time at 10, 50 and 100 calls.

### 3.10 Tools and the guard (D42–D46, D53)
- The model can only **ask** for actions through tools (e.g. `check_availability`,
  `book_visit`). Our code **decides**.
- The guard enforces business rules in code: opening hours, slot length, no double booking,
  no booking or change without the caller's explicit yes, after a read-back (D43, D44).
- The agent never promises anything the owner must confirm (D45).
- Facts (prices, timings) come only from the business config or tools — never made up.
- For clinic configs, a fixed emergency check runs every turn, outside the model (D53).
- Every tool call and every guard decision is written to the audit log (D46).

### 3.11 Human handoff (D47)
When the agent is unsure (two failed tries to understand, a request it can't serve, the
caller asks for a person), it offers to connect to the owner or takes a message. The message
and the notebook reach the owner through the queue.

### 3.12 Fallbacks (D48)
For each outside service (speech-to-text, model, text-to-speech, telephony):
1. Respect its rate limits.
2. Retry briefly (one quick retry; a live call can't wait long).
3. Switch to a backup provider (e.g. cloud model → second cloud model; Deepgram → Sarvam).
4. If all fail: play a short polite message and pass the call to the owner.

### 3.13 Message queue and background workers (D49)
Slow work never blocks the live call. When a call ends (or during it), the worker drops a
job on the queue; background workers do it:
- save the transcript and call record to Postgres,
- send the owner a call summary,
- update dashboard numbers and costs.

### 3.14 Postgres (D50)
Permanent records: businesses and their config versions, calls, bookings, messages for the
owner, the audit log. Every table has a `business_id`.

### 3.15 Monitoring dashboard (D51)
Shows active calls, reply time per turn, errors, cost per minute and per call. Alerts on
high reply time, error spikes, and spend reaching 80% of the monthly cap (D22).

### 3.16 Multi-tenant: one business = one config file (D8, D52)
The number that was called decides which config loads. A config holds:

```yaml
business_id: sunrise-clinic
type: clinic                # clinic | salon | pg
phone_numbers: ["+91..."]
languages: [en, hi]         # first greeting language + allowed languages
greeting: {en: "...", hi: "..."}
hours: {...}
services: [{name, duration_min, price}]
staff: [{name, services, schedule}]
faqs: [{q, a}]
rules: {min_notice_hours, max_days_ahead, double_booking: false}
tools: [check_availability, book_visit]
owner: {name, phone, handoff_hours}
safety: {emergency_check: true}   # clinics only
```

Adding a business means adding a file, not changing code.

### 3.17 Privacy (D54–D58)
- First seconds of every call: "You're speaking with the business's assistant; this call
  may be recorded."
- Collect only what a booking needs (name, phone, time, short reason).
- Personal data hidden in logs; stored safely; deleted on request.
- Recordings and transcripts deleted after 30 days; bookings kept.
- Exact DPDP Act requirements checked before the pilot (O4).

### 3.18 Languages (D11–D13)
Every prompt, greeting and fixed phrase is stored per language. Speech-to-text and
text-to-speech providers are chosen per language (Deepgram for English/Hindi; Sarvam for
Kannada and other Indian languages). English and Hindi (with Hinglish) work first.

## 4. One call, step by step

1. Staff miss a call; the business's phone forwards it to our number.
2. The telephony provider opens an audio stream; the load balancer pins it to a call worker.
3. The worker looks up the called number → loads that business's config (Redis) → creates a
   session and an empty notebook.
4. The agent greets the caller and says it's an assistant and the call may be recorded.
5. Caller speaks → speech-to-text → text added to the notebook.
6. Safety check (clinics) → router picks a model → request sent: fixed prefix + business
   knowledge + notebook.
7. The model replies or asks for a tool. Tools go through the guard; results go back to the model.
8. Before booking: read-back → caller says yes → guard books it → audit log entry.
9. Reply → text-to-speech → caller hears it. The caller can interrupt at any time.
10. Call ends → job on the queue → transcript saved, owner summary sent, dashboard updated.

## 5. What we measure (D59–D66)

| Measure | How |
|---|---|
| Missed calls answered without the owner | call outcomes in Postgres |
| Bookings captured; mistakes | outcomes + trace review; every mistake → new test call |
| Reply time per turn (goal ≈ 1 s) | timer per step: speech-to-text, model, tools, text-to-speech |
| Load: 10 → 50 → 100 concurrent calls | simulated text callers; reply time and errors at each level |
| Prefix caching effect | cached tokens and reply time, with vs without stable prefix |
| Cost per minute and per call | meter for speech, model tokens, telephony |
| Test pass bar | ≥ 90% scripted calls correct, zero dangerous failures |

## 6. Build order — milestones, one at a time (D67, D68)

No dates. Finish a milestone's **Exit** before starting the next.

### M1 — Design files
`docs/DECISIONS.md`, `docs/ARCHITECTURE.md`, `CLAUDE.md`.
**Exit:** you've read them, answered the 3 check questions, and given the go-ahead.

### M2 — Call-session core as a text simulator
- `CallSession` with its notebook and state in Redis.
- One business template (YAML) with FAQs and two tools: `check_availability`, `book_visit` (fake data).
- The guard (rules in code, explicit yes + read-back) and the audit log.
- A model client for any OpenAI-compatible server (default: local mlx on port 8080).
- A CLI to chat as a caller.
- pytest tests (guard, notebook, tools, model client with a fake server).
- **Exit:** you can book a visit by typing; the guard blocks double-booking and booking
  without a yes; tests green.

### M3 — Measure prefix caching on the local model
- Same conversations with and without the stable prefix; record cached tokens and reply time.
- **Exit:** a results table in `docs/RESULTS.md`.

### M4 — Load test with simulated concurrent text calls
- Many simulated callers at once against M2: 10, then 50, then 100.
- **Exit:** reply time and errors at each level recorded; the Mac's limit documented.

### M5 — Connect voice through Bolna
- Plug the session core into the Bolna setup: microphone first, then one real Twilio call.
- Browser demo link (D5).
- **Exit:** a natural voice booking end to end; reply time per step measured.

### M6 — Queue, background workers, owner summary, simple dashboard
- **Exit:** after every call the owner gets a summary; the dashboard shows active calls,
  reply time, errors and cost per call; the live call never waits on this work.

### M7 — Deploy to a cloud server; cloud model API for the pilot
- Postgres, Redis, workers on a cheap server; model via cloud API; budget alert at 80%.
- **Exit:** a real forwarded call answered from the cloud; cost per call measured;
  ready for gate 3.

## 7. Known risks

| Risk | Plan |
|---|---|
| The Mac can't serve many calls at once | Expected (D66); measure the limit; scale numbers come from cloud/vLLM. |
| Bolna limits under load | Load-test in M4/M5; switch voice layer to Pipecat/LiveKit (D28). |
| Names, numbers and dates misheard in Hinglish/Kannada | Keyterms, read-back, spell-back; Sarvam for Kannada. |
| Model invents prices or slots | Facts only from config/tools; guard decides; tests check it. |
| Outside service down or rate-limited | Retry → backup provider → polite message + owner (D48). |
| DPDP rules unclear | Check before the pilot (O4). |
