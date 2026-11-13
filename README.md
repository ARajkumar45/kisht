# Kisht — an EMI repayment agent for Indian lenders

[![CI](https://github.com/ARajkumar45/kisht/actions/workflows/ci.yml/badge.svg)](https://github.com/ARajkumar45/kisht/actions/workflows/ci.yml)

An AI agent that contacts borrowers about upcoming and missed EMIs, by **chat or voice**, in
**Hindi, English, Tamil or Telugu** (including Hinglish, Tanglish and Tenglish), and gets to an outcome: pay now, a promise to pay within the
lender's policy, or a hand-off to a human for hardship, disputes and waivers.

**The model plans and decides. Code guards only what must never go wrong** (RBI calling hours,
threats, money changes without a human, account details before identity). Every guard decision
is audited, so the split is measured, not claimed.

Runs **entirely on a laptop** (Qwen3.5-9B on Apple MLX) with every outside piece swappable.
Synthetic borrowers only — nobody real is ever contacted.

> Why this problem: Indian lenders pay for exactly this (e.g. Gnani reports ₹20 Cr/month
> recovered for one NBFC; Tata Capital uses Sarvam's voice agents), and it is regulated, which
> makes "let the model decide, but enforce the rules in code" a real engineering problem.

## What it does

```
kisht plan   ->  planner agent ranks today's due accounts: who first, chat or call, why, how
kisht chat   ->  conversation agent talks to the borrower (Hinglish example below)
kisht bridge ->  the same agent on a phone/mic call through the Bolna voice stack + Sarvam speech
evals/run.py ->  40 simulated borrowers x 4 runs, graded by code on the final ledger state
```

A real conversation on the local model (borrower lines typed by hand; agent unedited):

```
agent> Namaste, main Asha bol rahi hoon Demo Finance se. Kya meri baat Priya ji se ho rahi hai?
you>   Haan, main Priya bol rahi hoon.
agent> ... kya main aapka PIN code ya date of birth jaan sakti hoon?
you>   Mera PIN code 110004 hai.
agent> Priya ji, aapke 4450 rupaye overdue hain, 13 din se ... 17 November tak (allowed
       promise date) payment kar sakti hain, kam se kam 1113 rupaye ...
         [14.1s · 3 model calls · tools: verify_identity, get_dues]
```

## Who decides what

| The model decides (plans, chooses tools, adapts) | Code guards (tests prove each rule) |
|---|---|
| Today's queue: who first, chat or call, reason, approach (planner) | Contact only 08:00–19:00 lender time; daily/weekly attempt caps; opt-out; no calls to DND |
| The conversation: which tools, in what order, what to say | Identity (DOB or PIN) before any account detail; 3 misses lock |
| Answers from the loan agreement (RAG, cites the section) | Promise date and amount inside the lender's policy; one open promise |
| Negotiation: pay now / full promise / part payment | A promise is saved only after the borrower's own clear "yes" to the read-back |
| Spots hardship, dispute, wrong person → escalates | No tool can waive, settle or restructure — only escalate to a human |
| Writes the case note; reads past notes next time (memory) | Banned phrases blocked; this account's money/state never said before identity; claims of actions not taken ("link sent", "promise noted") replaced |

Tools never take a loan or borrower id: they act on the account bound to the conversation, so a
prompt injection cannot reach another borrower's data.

## Architecture

```mermaid
flowchart LR
  subgraph Channels
    CLI[chat CLI]
    Bolna[Bolna voice\nSarvam STT/TTS] --> Bridge[voice bridge\nOpenAI-compatible]
  end
  CLI --> Agent
  Bridge --> Agent
  Planner[planner agent] --> Guard
  Agent[conversation agent\nplan → tools → reply] --> Tools[tools]
  Tools --> Guard[policy guard\nrules from lender YAML]
  Agent --> Checks[reply checks\nbanned · leak · false claims]
  Guard --> Ledger[(ledger\nSQLite)]
  Guard --> Audit[(audit +\ntelemetry)]
  Agent --> State[(conversation state\nRedis)]
  Agent --> LLM{{LLM port}}
  Planner --> LLM
  LLM --> MLX[Qwen3.5-9B on MLX\nlocal default]
  LLM -.-> Other[Ollama · vLLM · cloud API]
  Tools --> RAG[loan agreement\nBM25 retrieval]
  Agent --> Insights[(call log · traces\nreviews · desk)]
  Reviewer[reviewer\nQA + analytics] --> Insights
  Reviewer --> LLM
  Insights --> API[API] --> Dash[React dashboard\nsupervisor · human desk]
```

Local-first, every outside piece behind a port chosen in `config.yaml`:

| Port | Default (this Mac) | Swap in |
|---|---|---|
| LLM, per role (agent, planner, simulator, reviewer) | Qwen3.5-9B on `mlx_lm.server` | Ollama, llama.cpp, vLLM, any OpenAI-compatible API |
| Speech (voice only) | Sarvam `saarika` / `bulbul` | other vendors via Bolna |
| Channel | chat CLI; mic/web via Bolna | phone (Plivo/Twilio via Bolna), WhatsApp |
| Store | SQLite ledger + Redis conversation state | Postgres |
| Policy / knowledge | `lenders/<id>.yaml`, `knowledge/<id>.yaml` | one pair per lender (multi-tenant) |

Each model server has a concurrency limit shared by every role on it plus a bounded queue
(this Mac runs 1–2 conversations at once; beyond that its GPU ran out of memory in a load test),
and a health check that runs a real completion.

## Languages

Everything that depends on language sits in one module per language under
`src/kisht/languages/`. Each module holds the lines code speaks, the yes, no and time words code
uses to judge the borrower, the phrases it uses to catch false claims by the agent, how to
recognise the language, and the Sarvam speech code. Words come in Latin letters for chat and in
native script, because Sarvam transcribes Indian-language speech in native script. Adding
Kannada or Bengali means adding one file, with no other code change.

Tamil and Telugu on the same local 9B model, 8 personas run twice each:

| Tamil / Telugu case | Run 1 | Run 2 (2 fixes) | Run 3 (3rd fix, promise only) |
|---|---|---|---|
| Pay now | 4/4 | 4/4 | |
| Promise to pay tomorrow | 1/4 | 1/4 | 4/4 |
| Stop messages | 3/4 | 2/4 | |
| Job loss, hand to a human | 0/4 | 2/4 | |
| Safety failures | 0 | 0 | 0 |

Each failed promise came from a real cause, and each was fixed in code:
- "yes, tomorrow morning" was read as a change of plan.
- The model repeated the same tool calls until the turn gave up.
- The model said "I'll record it" without calling the tool.

Hand-off on job loss is still weak, the same limit seen in Hindi.

One trap worth knowing: Python's `\w` and `\b` split Tamil and Telugu words at vowel signs, so
every word match here uses Indic-safe boundaries.

## Contact centre (CCAI)

The agent is one part of a contact-centre AI product. Kisht also has the parts around it, in a
React + TypeScript dashboard (`dashboard/`) served by `kisht serve`:

| Part | What it does here |
|---|---|
| Today's plan | The planner agent's queue for the day: who, which channel, and why in its own words, plus what each contact led to. |
| Call log | Every conversation, searchable, filterable by outcome, language, and "code blocked something"; exports to CSV. A date of birth or PIN code the borrower gives is masked before it reaches the log or the audit trail. |
| Call trace | Each call as an OpenTelemetry trace: every turn, model call (tokens, cache, queue wait), tool call and reply check, with timings. Blocked steps show in red. |
| Post-call QA | Every call is scored on the lender's QA scorecard by a reviewer model, with evidence. Contact centres usually score about 2% of calls by hand. |
| QA calibration | A human can mark the same scorecard on any call. Their marks are stored next to the AI's, never over them, and the Quality page shows how often the two agree and where they differ. Each scorecard item links to the calls that failed it. |
| Analytics | Why borrowers are not paying, their mood, outcomes, right-person contact rate, promise and link rates, money promised, containment (handled without a human), conversation length, and a per-language table. |
| Compliance | Counted by code, not judged by a model: threats, leaks before identity, false claims and out-of-policy actions the guard stopped. |
| Live view | Supervisor screen: conversations in progress and a feed of alerts. The supervisor can coach the AI with a private note for its next reply, or take the conversation over, which stops the AI and puts the case on the human desk. Both go through the guard and the audit log, and work across processes (a voice call on the bridge, coached from the dashboard). A note is guidance only: the reply still passes every check. |
| Human desk | Hand-offs routed to teams (hardship, disputes, collections manager) by rules in the lender YAML, each with a deadline (`desk_sla_hours`); the queue shows the most urgent first and flags late cases. Take, resolve, all audited. The resolution is saved with the borrower's case notes, so the AI knows what a human agreed the next time it talks to them. |
| Agent assist | For a human picking up a case: an AI brief, next best action, suggested replies in the borrower's language, and answers from the loan agreement with section numbers. |
| Test chat | A phone-style chat window to be the borrower against the real agent. |

![Overview: simulated and test conversations in Hindi, Tamil, English and Telugu](docs/img/overview.jpg)

A call with its post-call QA review, and its trace. The red "Reply check" is where the model
claimed the promise was saved before the borrower agreed; code replaced it with the read-back.

![Call detail with QA review](docs/img/call-review.jpg)
![Call trace](docs/img/trace.jpg)

The same agent in Tamil, and the human desk with agent assist on a hardship hand-off:

![Tamil conversation](docs/img/call-tamil.jpg)
![Human desk with agent assist](docs/img/desk.jpg)

The supervisor's live view. The supervisor's private note is shown above the reply it shaped;
the borrower's date of birth is already masked. "Take over" stops the AI and puts the case on
the human desk:

![Live view with coach and take over](docs/img/live.jpg)

The desk queue with deadlines, most urgent first; here the taken-over case is past its
one-hour deadline:

![Human desk queue with deadlines](docs/img/desk-queue.jpg)

A human checking the AI reviewer's marks on one call. Their marks start from the AI's and are
saved beside them, so agreement can be measured:

![Human QA check](docs/img/qa-check.jpg)

The planner's queue for the day, with its reasons and what each contact led to:

![Today's plan](docs/img/plan.jpg)

To fill it with a realistic day without contacting anyone, `kisht simulate` runs the planner and
then simulated borrowers with hidden situations against the real agent, guard and ledger:

```bash
uv run kisht simulate --n 20        # plan today, 20 simulated conversations, each reviewed
uv run kisht review                 # review any call not yet reviewed (--all: review again)
cd dashboard && npm install && npm run build && cd ..
uv run kisht serve                  # http://127.0.0.1:8000
uv run kisht serve --at 2026-11-12T11:00:00+05:30   # fixed clock: test chat outside 08:00-19:00
```

A conversation is wrapped up the same way whoever ended it: a case note for next time, the
ledger contact closed, and the review. A phone call that simply goes quiet is picked up by a
sweeper after a few minutes.

The dashboard has no login. It is built for a local demo; put it behind authentication before
exposing it to a network.
The voice bridge accepts any caller on this machine by default. Before it is reachable from
outside (a tunnel for a phone provider, Docker), set `KISHT_BRIDGE_TOKEN` for both `kisht
bridge` and `tools/run_bolna.sh`: the bridge then requires it as a bearer token. Docker
publishes both ports on 127.0.0.1 only.

Traces go to the dashboard's store. Set `tracing.otlp_endpoint` in `config.yaml` to send the
same spans to Jaeger, Arize Phoenix or Grafana Tempo as well.

## Evaluation

Full run, everything local: Qwen3.5-9B (4-bit, MLX) as both agent and simulated borrower,
40 personas x 4 runs = 160 conversations, 0 errors, median 15.5 s per turn on an M-series Mac.

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

**Safety held in all 160 runs:** no banned phrase reached the borrower and no account detail was
shared before identity was verified. That is the guard's job, not the model's: code replaced
108 replies and blocked 30 out-of-policy actions.

| What code blocked or replaced | Count |
|---|---|
| Agent said "promise saved" when it was not | 57 |
| Agent said "link sent" without sending one | 19 |
| Loan detail before identity was verified | 12 |
| Threat or banned phrase | 10 |
| Waiver or "payment received" claim | 10 |
| Promise date beyond the lender's limit | 14 |
| Part payment below the lender's minimum | 7 |
| Wrong date of birth / PIN | 8 |

**Error analysis changed the code, not just the prompt.** The first run (124 of 160 conversations)
passed 39%. Reading the failures showed borrowers confirm a promise by repeating it ("haan, kal
11 November ko 3000"), and the yes-check treated any date or number as a change request, so no
promise was ever saved. After fixing that (D88) the same personas pass 63%, and 67% over the full
suite. Both runs are in `results/evals/`.

These numbers were measured before later fixes that also apply to Hindi and English (promise
confirmation with a time of day, repeated tool calls, "I'll record it" without the tool,
dates in words), so they are a floor, not the current score.

**What still fails, and why:** a 9B local model under-uses `escalate_to_human` (disputes,
waivers) and often answers fee questions from memory instead of calling `lookup_agreement`.
Code keeps these failures safe (nothing false is promised), but the borrower is not routed. The
next steps are a larger model through the same adapter (a config change) and a code-side route
for "already paid" claims.

Method (τ-bench / τ²-bench): an LLM plays a borrower with a hidden persona; the real agent talks
to it; success is judged **by code on the final ledger state** (right promise saved? escalated
with the right reason? nothing revealed to a stranger?) plus safety checks on every reply. Each
persona runs 4 times; we report pass^1 and pass^4 (all 4 succeed). 40 personas in 10
categories: pay now, promise, negotiate, hardship, waiver, dispute, identity, opt-out, questions
about terms, and adversarial (rudeness, prompt injection, "make the agent threaten me").

## Run it

```bash
uv sync
mlx_lm.server --model mlx-community/Qwen3.5-9B-4bit --port 8080   # or any OpenAI-compatible server
brew services start redis
uv run python tools/make_loan_book.py      # 200 synthetic borrowers
uv run kisht health                        # each model role answers a real completion
uv run kisht plan                          # today's outreach queue
uv run kisht chat --borrower br_0009       # be the borrower
uv run pytest -q                           # tests
uv run python evals/run.py --k 4           # evals (hours on a laptop; resumable)
```

Voice: `tools/run_bolna.sh` (Bolna fork from source), `uv run kisht bridge`, then
`uv run python tools/make_voice_agent.py br_0009 --post` and talk through Bolna's mic client.
The same script asks the bridge to prepare the call (the model reads that borrower's
instructions while the phone rings), and on the call each sentence is spoken as soon as it is
written and checked, so the borrower hears the first words after about 1-2 s on the local
model instead of waiting for the whole reply (docs/DECISIONS.md, D108).

### Docker

The app and Redis run in containers. The model server stays on the host, because containers
cannot use the Mac GPU. Tested from a fresh clone: the first start builds the 200-borrower
loan book, and a full Hindi promise-to-pay conversation through the bridge saved the promise,
the payment link and the follow-up in the ledger.

```bash
mlx_lm.server --model mlx-community/Qwen3.5-9B-4bit --port 8080   # on the host
docker compose up -d --build                         # bridge on :5050, dashboard on :8000
docker compose exec kisht ./docker-entrypoint.sh health
docker compose run --rm kisht chat --borrower br_0009
```

No Mac? `docker compose --profile ollama up` starts an Ollama server too; point
`config.docker.yaml` at it.

## Layout

```
src/kisht/   ports.py adapters/ config.py   interfaces and swappable adapters
             agent.py prompt.py confirm.py   conversation agent and reply checks
             planner.py                      planner agent
             guard.py tools.py               policy guard and the tools the model can use
             ledger.py loanbook.py           loan book and synthetic data
             knowledge.py                    BM25 retrieval over the loan agreement
             languages/                      one module per language (en, hi, ta, te)
             insights.py tracing.py          call log, OpenTelemetry traces, desk state
             review.py simulate_day.py       post-call QA + analytics; simulated day
             api.py runtime.py               dashboard API; one builder for every process
             evals.py voice_bridge.py cli.py
dashboard/   React + TypeScript contact-centre dashboard
lenders/ knowledge/ evals/personas.yaml config.yaml
docs/        decisions, research and measured results
```

## Licence

MIT. See `LICENSE`.

## History

This repository started as a salon phone receptionist (milestones M1–M5, tag `receptionist-m5`),
which built and measured the infrastructure Kisht reuses: 10× faster prompt processing from a
byte-stable prompt prefix, 100 concurrent simulated callers with zero double bookings, and an
end-to-end voice turn over Bolna + Sarvam (voice layer ≈ 1.5 s per turn). The domain changed
because Indian customers rarely book salons by phone and the model had too little to decide.
