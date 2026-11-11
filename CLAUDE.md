# CLAUDE.md — Kisht

## Project summary
Kisht is an EMI repayment agent for Indian lenders with a contact-centre dashboard around it.
The model plans and decides; code guards what must never go wrong. Runs fully local.

- What it is and how to run it: `README.md`
- Design: `docs/ARCHITECTURE.md` · Decisions: `docs/DECISIONS.md` · Numbers: `docs/RESULTS.md`
- Local model: Qwen3.5-9B (4-bit) via `mlx_lm.server`, OpenAI-compatible, port 8080
- Python 3.12 via `uv`; dashboard in `dashboard/` (React + TypeScript, Vite)

## Rules
- Synthetic borrowers only. Never contact a real person.
- Secrets live in `.env`, which is never committed. Never print or commit a key.
- Every change keeps `uv run pytest -q`, `uv run ruff check src tests` and
  `cd dashboard && npm run build` green.
- A new guard rule or reply check comes with a test that shows the failure it prevents.
- Measured numbers go in `docs/RESULTS.md` with how they were measured.
