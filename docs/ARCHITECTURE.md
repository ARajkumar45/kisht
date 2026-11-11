# Architecture — Kisht

How the system is put together and why. Decision numbers (D88 and up) point to
`docs/DECISIONS.md`; measured numbers are in `docs/RESULTS.md`.

## 1. In one paragraph

Kisht contacts borrowers about EMIs that are due or overdue, by chat or voice, in Hindi,
English, Tamil or Telugu. A planner agent decides each morning who to contact and why. A
conversation agent then runs each conversation: it verifies identity, reads the dues, and
works out an outcome with the borrower (pay now, a promise to pay, a part payment, or a
hand-off to a human). A policy guard, written in code and configured per lender, stands
between the model and anything that must never go wrong. Around the agent sits a contact
centre: call log, traces, automatic QA, a human desk and agent assist.

## 2. The one design rule

**The model decides. Code guards.**

| The model decides | Code guarantees |
|---|---|
| Who to contact first, by which channel, and why | Calling hours, attempts per day and week, opt-outs and do-not-disturb |
| The whole conversation and which tools to use | No loan detail before identity is verified |
| How to negotiate: full, part, or a date | Promise date and amount inside the lender's limits |
| When a case needs a human | Waivers, settlements and restructuring can only be escalated, never granted |
| The case note, and how to use past notes | A promise is saved only on the borrower's clear yes to a read-back |
| | Nothing false is said: "promise saved", "link sent", "payment received" must be backed by a real action |
| | No threats or shaming phrases reach the borrower |

Every time code refuses an action or replaces a reply, it is recorded. That record is the
guard telemetry in the README and the "blocked" counts in the dashboard.

## 3. The parts

```
channels          chat CLI · dashboard test chat · voice (Bolna + Sarvam -> voice bridge)
                        |
agents            planner (the day's queue)      conversation agent (plan -> tools -> reply)
                        |                               |
                        +-----------> tools ------------+----> reply checks
                                        |
guard             policy guard: rules from lenders/<id>.yaml, every decision audited
                        |
stores            ledger (SQLite) · conversation state (Redis) · audit files
                        |
contact centre    insights store: call log, turns, OpenTelemetry spans, reviews, desk state
                  reviewer (QA + analytics) · wrap-up sweeper · API · React dashboard
```

| Module | What it does |
|---|---|
| `ports.py`, `adapters/` | Small interfaces (chat model, conversation state) and their adapters. The model adapter has a per-server concurrency limit and queue. |
| `config.py`, `runtime.py` | `config.yaml` picks the model per role (agent, planner, simulator, reviewer) and the stores. `runtime.build` assembles the same parts for every process. |
| `lender.py` | One YAML per lender: calling window, limits, banned phrases, QA scorecard, desk teams. |
| `ledger.py`, `loanbook.py` | The loan book. Checked writes run in one transaction each. Synthetic data generator. |
| `guard.py`, `tools.py` | The policy guard and the eight tools the model may call. No tool takes a borrower or loan id: a conversation is bound to one account. |
| `agent.py`, `prompt.py`, `confirm.py` | The conversation loop, the prompt (stable prefix for caching), and the checks on what the borrower and the agent say. |
| `languages/` | One module per language: what code says, the words it listens for, how to recognise the language. |
| `planner.py` | The planner agent: batches of accounts in, a ranked queue with reasons out, filtered by the guard. |
| `knowledge.py` | Retrieval over the loan agreement (BM25), answers cite section numbers. |
| `evals.py`, `simulate_day.py` | Simulated borrowers: a graded test suite, and a simulated working day. |
| `insights.py`, `tracing.py` | Call log and OpenTelemetry tracing (one trace per call). |
| `review.py`, `wrapup.py` | Post-call QA and analytics; closing conversations properly, including calls that just go quiet. |
| `api.py`, `dashboard/` | The contact-centre API and the React + TypeScript dashboard. |
| `voice_bridge.py` | An OpenAI-compatible endpoint that Bolna uses as its "LLM", so a phone call reaches the same agent. |

## 4. One conversation, step by step

1. The guard checks the contact rules (hours, attempts, opt-out). If they fail, nothing starts.
2. Code greets in the borrower's language. The model has not seen any account detail yet.
3. The borrower replies. The model asks for date of birth or PIN and calls `verify_identity`.
4. On success the model calls `get_dues` and gets the facts: amounts, dates in words, limits,
   past case notes, today's plan for this account.
5. The model negotiates and calls tools. Each call passes the guard; a refusal comes back with
   the reason, and the model adapts.
6. A promise is read back by code and saved only on a clear yes.
7. Before any reply is sent, code checks it. A bad reply gets one retry, then is replaced.
8. At the end: case note, ledger contact closed, post-call review. A sweeper does the same for
   calls that went quiet.

## 5. What is measured

- **Evals:** 48 personas, each run several times, graded by code on the final ledger state
  plus safety checks on every reply. Reported as pass^1 and pass^k.
- **Guard telemetry:** what code blocked, by rule.
- **Per call:** a trace with timings, tokens and cache use; a QA score; compliance counts.

## 6. Known limits

- The default 9B local model under-uses escalation and agreement lookup. Code keeps those
  failures safe, but the borrower is not always routed. A larger model is a config change.
- The simulated borrower and the QA reviewer are the same small model as the agent. The
  reviewer is given the recorded facts (D99), but its judgement has not been measured against
  human labels yet.
- The dashboard API has no login. It is built for a local demo; put it behind authentication
  before exposing it.
- Voice in Tamil and Telugu is configured but has only been tested as text.
