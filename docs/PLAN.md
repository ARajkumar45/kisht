# Build Plan — AI Receptionist (Sunrise Multispeciality Clinic, Bengaluru)

This plan turns `docs/DECISIONS.md` into work. Decision numbers (D1…D34) are cited
so every piece of work traces back to a decision. Choices from section 12 were accepted on 2026-11-08 as D35–D42. There are no dates:
each phase starts when the previous phase's exit criteria are met (D42).

---

## 1. What we are building, in one paragraph

A voice receptionist for a multi-doctor clinic. A caller reaches it through a browser
link, later a phone number. It says it is an AI and that the call is recorded, understands English,
Hindi and Hinglish, and books, moves or cancels appointments by calling tools on the
clinic's schedule. It answers questions only from clinic data, catches emergencies with a
fixed rule check, and hands off to staff when it is stuck. Every call is traced, tested
against a 50+ call test suite on every change, and costed per call. Runs free on a Mac
first, then on a cheap cloud server for a real clinic pilot.

## 2. Starting point (checked on this Mac, 2026-11-08)

| Item | Status | Meaning for the plan |
|---|---|---|
| Apple M5, 16 GB RAM, 197 GB free | ok | A 9B 4-bit model (~6 GB) plus STT/TTS clients fit. 14B+ would not leave room. |
| `mlx-community/Qwen3.5-9B-4bit` | already downloaded | Use it (D12 said 7–8B; 9B is close; confirm latency in Phase 1). |
| Python 3.15 system-wide | too new for many voice libs | Pin Python 3.12 per project with `uv` (installed). |
| `uv`, Docker, Node, `gh` | installed | Docker for gate 3 images; `gh` for the public repo. |
| `mlx` / `mlx-lm`, `ffmpeg`, tunnel (`cloudflared`) | missing | Install in Phase 0. |
| `bolna_project` | your ATM voice agent + Deepgram WER study | Reuse the WER method and keyterm finding (Nova-3 + keyterms cut WER ~55%). |
| `retail-agent` | "model asks, store decides" + audit log | Reuse the pattern: booking rules enforced in code, not in the prompt. |
| `eval-harness` | AI judge vs human labels | Reuse as the judge for open-ended calls. |
| `tau2-bench` | simulated users, voice, multilingual | Borrow the simulated-caller approach for the test suite. |

## 3. Architecture

```
            ┌────────────── Access (adapters, D16) ───────────────┐
 Caller ──► │ Browser WebRTC (gate 1) │ Twilio (gate 2) │ Indian no. (gate 3) │
            └───────────────────────────┬─────────────────────────┘
                                        │ audio frames
                    ┌───────────────────▼────────────────────┐
                    │        Voice pipeline (per call)       │
                    │  VAD/turn-taking → STT → Agent → TTS   │
                    │   (Deepgram)       │      (Kokoro/Sarvam)
                    └──────────┬─────────┼──────────┬────────┘
                               │         │          │
                 ┌─────────────▼──┐ ┌────▼─────┐ ┌──▼──────────────┐
                 │ Safety layer   │ │ LLM      │ │ Tracing + cost  │
                 │ emergency rules│ │ adapter  │ │ (every turn)    │
                 │ (every turn)   │ │ Qwen/MLX │ └─────────────────┘
                 └────────────────┘ └────┬─────┘
                                         │ tool calls only
                    ┌────────────────────▼───────────────────┐
                    │ Clinic service ("store decides")       │
                    │ doctors, slots, bookings, rules, audit │
                    │ per-clinic data (D18)  SQLite→Postgres │
                    └───────┬─────────────────────┬──────────┘
                            │                     │
                    Staff dashboard        Confirmations
                    (fix/cancel, alerts)   (SMS/WhatsApp, D30)
```

**Key design rules**
1. **Adapters for everything paid (D11):** `LLM`, `STT`, `TTS`, `Telephony`, `Notifier`
   are interfaces. Choosing a provider is a config line, not a code change.
2. **The model asks, the clinic service decides** (from `retail-agent`): no double-booking,
   working hours, slot length, and cancellation rules are enforced in code. A bad model reply cannot
   break a rule (D7: zero double-booked slots).
3. **Safety runs outside the model (D28):** the emergency check runs on every caller
   turn before the model sees it, and can interrupt the pipeline.
4. **Answers come only from tools (D31):** the prompt has no clinic facts; doctors, timings and
   fees come from tool results.
5. **Per-clinic separation from day one (D18):** every table and every config has a `clinic_id`;
   one process can serve many clinics.

## 4. Stack

| Layer | Gate 1 (₹0) | Gate 2 (small top-up) | Gate 3 (≤ ₹3,000/mo) |
|---|---|---|---|
| Voice framework | **Pipecat** (D35) | same | same |
| Access | Pipecat SmallWebRTC in browser | + Twilio upgraded number | + Exotel/Plivo Indian number (clinic KYC) |
| STT | Deepgram Nova-3 streaming, `multi`/hi+en, keyterms | same | same |
| LLM | Qwen3.5-9B-4bit, `mlx_lm.server` (OpenAI-compatible) | same, Mac via tunnel | hosted cheap model (Groq / OpenRouter Qwen) if server can't run it |
| TTS | Kokoro (local) | Sarvam Bulbul | Sarvam Bulbul; ElevenLabs as premium swap |
| Data | SQLite | SQLite | Postgres (managed or on the server, India region) |
| Hosting | Mac | Mac + `cloudflared` tunnel | Small cloud VM in Mumbai region (e.g. Hetzner/DigitalOcean/AWS Lightsail ap-south-1) |
| Tracing | Langfuse (self-hosted, Docker) or OpenTelemetry → local | same | same, on server |
| Dashboard | FastAPI + HTMX pages | same | same, behind login |
| CI | GitHub Actions | same | + deploy job |

**Latency budget (target: median < 1.2 s, slowest 5% < 2.5 s; D8)**

| Step | Budget |
|---|---|
| End-of-speech detection (VAD + Deepgram endpointing) | 300 ms |
| STT final transcript | 150 ms |
| Safety check | < 10 ms |
| LLM first tokens (Qwen 9B, thinking off, short prompt, cached prefix) | 400 ms |
| TTS first audio chunk | 250 ms |
| Network/transport | 100 ms |
| **Total to first audio** | **~1.2 s** |

Tricks if over budget: stream LLM → TTS by sentence; keep the system prompt short and
prefix-cached; disable Qwen "thinking"; filler phrase ("One moment, checking Dr. Rao's
slots…") while a tool runs; smaller model as fallback.

## 5. Repository layout

```
ai-receptionist/
├── CLAUDE.md                    # short pointer to DECISIONS.md + PLAN.md + conventions
├── README.md                    # recruiter-facing: demo link, architecture, results, trade-offs
├── docs/
│   ├── DECISIONS.md
│   ├── PLAN.md
│   ├── ARCHITECTURE.md          # diagrams, latency budget, adapter contracts
│   ├── PRIVACY.md               # DPDP notice text, data map, retention, deletion process
│   ├── RUNBOOK.md               # what to do when it breaks (gate 2+)
│   └── RESULTS.md               # test-suite scores, latency, cost, pilot numbers over time
├── pyproject.toml / uv.lock     # Python 3.12
├── src/receptionist/
│   ├── config/                  # settings, per-clinic config loader
│   ├── adapters/                # llm/, stt/, tts/, telephony/, notify/  (interfaces + impls)
│   ├── clinic/                  # models, repository, rules, booking service, audit
│   ├── agent/                   # prompt, tool definitions, conversation state, handoff logic
│   ├── safety/                  # emergency rules (hi/en), PII redaction, consent handling
│   ├── pipeline/                # Pipecat pipeline assembly per access channel
│   ├── tracing/                 # spans, latency timers, cost meter, budget guard
│   ├── dashboard/               # FastAPI + HTMX staff UI
│   └── server.py                # entrypoint
├── clinics/sunrise/             # fictional clinic: doctors.yaml, hours.yaml, fees.yaml, faq.yaml
├── evals/
│   ├── scenarios/               # 50+ scripted calls (YAML): goal, persona, language, expected outcome
│   ├── simulator/               # LLM caller simulator (text) + TTS-voiced mode
│   ├── graders/                 # rule checks (booking state, forbidden phrases) + LLM judge
│   └── run.py                   # runs suite, writes report + RESULTS.md table
├── tests/                       # unit tests (rules, safety, redaction, adapters)
├── tools/                       # text_chat.py, mic_chat.py, load_test.py, seed.py
├── deploy/                      # Dockerfile, compose, server setup, backup
└── .github/workflows/           # ci.yml (lint, unit, eval subset), deploy.yml
```

## 6. Clinic data and tools

**Fictional clinic (D3):** Sunrise Multispeciality Clinic, Indiranagar, Bengaluru.
6 doctors (general physician ×2, paediatrics, gynaecology, orthopaedics, dermatology),
OPD 9:00–13:00 and 17:00–20:00, Sunday morning only, 15-min slots, fees ₹400–800.

**Tables (all with `clinic_id`):** `doctors`, `schedules`, `leaves`, `slots`, `patients`
(name, phone only), `appointments` (doctor, slot, short reason, status), `calls`
(metadata, consent flag, outcome), `handoffs`, `audit_log`, `deletion_requests`.

**Tools the model may call:**

| Tool | Notes |
|---|---|
| `find_doctors(specialty?, name?)` | from clinic data only |
| `get_available_slots(doctor_id, date_from, date_to, part_of_day?)` | returns max 3 options to read out |
| `book_appointment(doctor_id, slot_id, patient_name, phone, reason_short)` | service re-checks slot; rejects if taken; needs `confirmed=true` after read-back (D30) |
| `find_appointments(phone)` | caller's own phone only (caller ID or stated + read back) |
| `reschedule_appointment(appointment_id, new_slot_id)` / `cancel_appointment(appointment_id)` | confirm first |
| `get_clinic_info(topic)` | hours, address, fees, parking, insurance, from `faq.yaml` |
| `request_callback(reason)` / `transfer_to_staff(reason)` | D21, D29 |

## 7. Conversation design

1. **Opening (D21):** "Namaste, Sunrise Clinic. I'm the clinic's AI assistant; this call is
   recorded to help book appointments. Say 'staff' anytime to talk to a person. How can I help?"
   (Language follows the caller after the first reply.)
2. **Recording objection (D22):** stop recording flag, keep going, store booking only.
3. **Main jobs:** book / reschedule / cancel / doctor availability / clinic info.
4. **Read-back before any change (D30):** "Dr. Rao, Tuesday 12th, 10:30 a.m., for Priya — shall I book?"
5. **Stuck counter (D29):** 2 failed understandings → offer transfer or callback.
6. **Unknown fact (D31):** "I don't have that; I'll have staff confirm and call you back."
7. **Emergency (D28):** safety layer interrupts → fixed script with 108/112 → staff alert → end or stay.
8. **Closing:** summary + "you'll get an SMS confirmation".

Names, phone digits and dates in Hinglish are the hardest STT cases. Use Deepgram keyterms
(doctor names, area names), spell-back for phone numbers, and an 8 kHz phone-audio WER test
like the one in `bolna_project`.

## 8. Testing and evaluation (the core of "production grade", D7, D8, D33)

**Unit tests** (`tests/`): booking rules (no double-book, hours, leaves, past dates),
emergency rules (Hindi/English/Hinglish phrases, no false negatives on a fixed list),
PII redaction, budget guard, adapter contracts.

**Scenario suite** (`evals/scenarios/`, 50+ at gate 1, grows with D33):

| Category | ~Count | Example |
|---|---|---|
| Book new appointment | 12 | Hinglish, wants "kal subah" with a paediatrician |
| Reschedule / cancel | 8 | wrong phone first, then corrects |
| Clinic info | 8 | fees, parking, Sunday hours |
| Unknown / out of scope | 5 | "do you accept Star Health?" (not in data) → staff confirm |
| Medical advice bait | 5 | "what dose of paracetamol?" → refuse politely |
| Emergency | 6 | "papa ko chest pain ho raha hai" → 108/112 script |
| Handoff / stuck | 4 | asks for staff; mumbles twice |
| Consent objection | 2 | "don't record me" |
| Adversarial | 3 | prompt injection, asks for other patient's data |

**How a scenario is graded**
- *Hard checks (code):* final DB state equals expected (right doctor/slot/status), no
  double-book, forbidden phrases absent, emergency script present when required, handoff
  called when required. Any dangerous failure fails the run (D7).
- *Soft checks (LLM judge from `eval-harness`):* politeness, read-back done, language
  matched caller. The judge is checked against ~30 hand labels; agreement is reported.

**Modes:** text simulator (fast, every commit runs a 15-scenario subset in CI; full suite
nightly/on demand), voice mode (simulator lines voiced by TTS → full pipeline, measures
latency and STT errors), human mic sessions (manual, logged).

**Load test (D18):** N simultaneous simulated calls; report latency vs N and the breaking point.

## 9. Observability, cost and budget guard

- One trace per call; one span per turn and per step (VAD, STT, safety, LLM, tool, TTS).
- Stored: redacted transcript, tool calls, latencies, outcome label, cost estimate.
- Cost meter: STT seconds × price, TTS characters × price, LLM tokens × price, telephony minutes.
  Prices in config so swaps update the dashboard automatically.
- Budget guard (D10): monthly total checked before answering each call; ≥ 80% → alert;
  ≥ 100% → telephony adapter returns "don't answer" → clinic's normal ringing/voicemail.
- Retention job (D25): nightly delete of recordings/transcripts older than 30 days.

## 10. Phases, tasks and exit criteria

No dates (D42). A phase is done when its **Exit** line is met, and only then does the next one start.
The sizes below are rough effort guides, not deadlines.

### Phase 0 — Foundation (≈ 2–3 days)
- Repo skeleton (§5), `uv` + Python 3.12, ruff, pytest, pre-commit, GitHub Actions running lint + unit tests.
- Install `mlx-lm`, `ffmpeg`, `cloudflared`; start `mlx_lm.server` with Qwen3.5-9B-4bit; measure first-token time.
- `CLAUDE.md` with conventions and pointers; `.env.example`; secrets never committed.
- **Exit:** `uv run pytest` green in CI; local model answers an OpenAI-style request in < 500 ms first token.

### Phase 1 — Clinic brain in text (≈ 1 week)
- Clinic data model + `sunrise` seed data; booking service with rules + audit log; unit tests.
- Tool definitions; agent prompt; conversation state (stuck counter, read-back gate).
- Safety layer v1: emergency rules (hi/en/Hinglish), medical-advice refusal, PII redaction.
- `tools/text_chat.py` — talk to the agent in the terminal.
- **Exit:** you can book/reschedule/cancel by typing; double-booking impossible by test.

### Phase 2 — Test suite and tracing (≈ 1 week)
- Scenario format + 50 scenarios; text caller simulator; hard graders; LLM judge + 30 hand labels.
- Tracing (per call/turn/step) + cost meter; `RESULTS.md` auto-table.
- CI runs the 15-scenario subset on every push.
- **Exit:** suite runs end-to-end, baseline score recorded (expect < 90% — that's fine).

### Phase 3 — Voice on the Mac (≈ 1 week)
- Pipecat pipeline: browser WebRTC → VAD → Deepgram → safety → Qwen → Kokoro.
- Sentence streaming, filler during tool calls, barge-in (caller interrupts agent).
- Consent opening + objection path. `tools/mic_chat.py`.
- Voice-mode eval: voiced scenarios, latency per step; 8 kHz Hinglish WER mini-study with keyterms.
- **Exit:** natural browser call works; latency measured.

### Phase 4 — Hit gate 1 (≈ 1 week, iterative)
- Fix failures until suite ≥ 90% and zero dangerous failures (D7); latency median < 1.2 s, slowest 5% < 2.5 s.
- Staff dashboard v1: today's bookings, fix/cancel, handoff and emergency alerts.
- Notifier adapter (console/email stub at ₹0).
- README v1 with architecture, numbers, demo video (screen recording of a browser call).
- **GATE 1 PASSED → repo public** (D39). Spend so far: ₹0.

### Phase 5 — Gate 2: friends by phone (≈ 1 week, small top-up)
- Twilio trial for 2–3 test calls → upgrade + number; Twilio telephony adapter; Mac reachable via `cloudflared`.
- Switch TTS to Sarvam Bulbul; compare with Kokoro on 10 lines (blind preference by friends).
- SMS confirmation via Twilio (D30).
- 10–20 friend calls with a short script + free-form; every failure → new scenario (D33).
- Load test on Mac: 2 simultaneous calls stable (D17).
- **Exit:** friends' calls ≥ 90% correct by trace review; suite still green; cost per call known.

### Phase 6 — Production hardening (≈ 1–2 weeks)
- Postgres + migrations; per-clinic config and data separation tests (D18).
- Docker image; deploy to India-region VM; HTTPS; dashboard login; backups.
- LLM adapter for a hosted model; A/B on the suite vs local Qwen (score, latency, cost).
- Budget guard live (D10); retention job (D25); deletion request path (D26).
- `PRIVACY.md` (notice text, data map, processors: Deepgram, Sarvam, host) and `RUNBOOK.md`.
- Load test on server: find the breaking point; document it.
- **Exit:** one-command deploy from CI; all D-items for gate 3 in place with test data.

### Phase 7 — Gate 3: real clinic pilot (2 weeks live)
- Find a clinic (outreach list, one-page pitch with demo link + privacy summary).
- Data agreement signed (D26); load their doctors/hours; Indian number on their KYC; overflow forwarding from their line.
- Week 1: shadow mode (agent only after-hours). Week 2: rush-hour overflow.
- Daily trace review; failures → scenarios; weekly report to the clinic.
- **Exit / headline (D6):** ≥ 80% of answered calls resolved; count of missed calls turned into bookings; cost per booking.

### Phase 8 — After gate 2/3 (backlog)
- Kannada (D20); WhatsApp confirmations; more clinics (D18); premium TTS trial.

## 11. Risks and how we handle them

| Risk | Likelihood | Plan |
|---|---|---|
| Local Qwen too slow for < 1.2 s median | Med | Measure in Phase 0; thinking off; shorter prompt; fall back to a smaller local model or hosted model. |
| Hinglish names/numbers misheard | High | Keyterms, spell-back, read-back, WER study; scenarios for it. |
| Kokoro sounds poor in Hindi | High | Accept for gate 1; Sarvam at gate 2 (D14). |
| Model ignores tool rules / invents slots | Med | Rules in code, answers only from tools, hard graders. |
| Emergency missed | Low, severe | Rule layer independent of model; zero-tolerance tests; staff alert. |
| No real clinic agrees | Med | Gates 1–2 still give a strong portfolio; pitch with demo + privacy doc; offer free 2-week pilot. |
| Indian number KYC blocks gate 3 | Med | Clinic forwards missed calls to Twilio/Exotel number registered in their name; or WebRTC link on their site. |
| Mac sleeps / tunnel drops at gate 2 | Med | `caffeinate`, auto-restart script, health check; acceptable for friend tests. |
| Python 3.15 incompatibilities | High | Pin 3.12 via `uv`. |

## 12. Build choices (all settled 2026-11-08 → D35–D42)

| # | Choice | Recommendation | Needed by |
|---|---|---|---|
| Q1 | Voice framework | **Pipecat**: open source, built-in adapters for Deepgram/Twilio/WebRTC/Sarvam/OpenAI-compatible LLMs, widely used in industry. Shows range beyond your Bolna project. (Alternatives: your Bolna fork, LiveKit Agents, custom.) | Phase 3 |
| Q2 | Model size | Use the downloaded **Qwen3.5-9B-4bit**; drop to a smaller one only if latency misses budget. | Phase 0 |
| Q3 | Tracing tool | **Langfuse self-hosted** (nice UI for demos) vs plain OpenTelemetry + own dashboard. | Phase 2 |
| Q4 | Cloud host for gate 3 | Cheapest **Mumbai-region VM** (~₹500–1,000/mo) + managed Postgres only if within cap. | Phase 6 |
| Q5 | Pacing | No dates; move on when the exit criteria are met (D42). | — |
| Q6 | Public repo | **Public after gate 1**, MIT license, no secrets, fictional data only. | Phase 4 |
| Q7 | Confirmations | SMS via Twilio at gate 2; WhatsApp later (needs Meta business verification). | Phase 5 |
