# Kisht — an EMI repayment agent for Indian lenders

*Work in progress.* An AI agent that reminds borrowers about upcoming and missed EMIs, by chat or
voice, in Hindi, English or Hinglish. **The model plans and decides; code guards only what must
never go wrong** (RBI calling hours, threats, money changes without a human, identity before
account details).

- **Model decides:** today's contact queue, chat or call, the whole conversation, which tools in
  which order, answers from the loan agreement, negotiating a date or part payment, when to hand
  a case to a human, the case note.
- **Code guards:** calling window 08:00–19:00, attempt caps, opt-out, identity check, promise
  limits from the lender's policy, waivers/settlements only via a human, banned phrases, and an
  audit record for every proposal and every block.

Synthetic borrowers only; nobody real is ever contacted.

## Architecture: local-first, every outside piece swappable

| Port | Default (runs on this Mac) | Swap in via `config.yaml` |
|---|---|---|
| LLM, per role (agent, planner, user simulator) | Qwen3.5-9B on `mlx_lm.server` | Ollama, llama.cpp, vLLM, any OpenAI-compatible cloud API |
| Speech (voice only) | Sarvam STT/TTS | open models later |
| Channel | terminal chat; web/mic via Bolna | WhatsApp, phone |
| Store | SQLite ledger + Redis conversation state | Postgres |
| Policy | `lenders/<id>.yaml` | one file per lender |

Each model server gets a concurrency limit shared by all roles on it (this Mac runs 1–2
conversations at once; beyond that its GPU ran out of memory in our load test) and a health check
that runs a real completion.

## Status

Built step by step; see `docs/` for decisions and measured results. M1–M5 of this repository
built and measured the voice/LLM infrastructure (as a salon receptionist): 10× prompt-cache
speed-up, 100 concurrent simulated callers with zero double bookings, an end-to-end voice turn
over Bolna + Sarvam. That code is being converted into Kisht now.

## Run the tests

```bash
uv sync && uv run pytest -q
```
