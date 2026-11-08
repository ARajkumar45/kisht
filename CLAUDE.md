# CLAUDE.md — AI Receptionist

## Project summary
An AI phone receptionist for small businesses in Bengaluru, India. It answers the calls
staff miss (call forwarding), answers questions from the business's config, and books
visits only after the caller says yes. Each business is one config file. Built solo,
production-grade, designed to handle many calls at once and sell to more businesses.
Free and trial tools first; money is spent only at three gates (₹0 → small top-up →
≤ ₹3,000/month pilot).

- Decisions: `docs/DECISIONS.md` (one line each, plus open questions)
- System design and milestones: `docs/ARCHITECTURE.md`
- Voice engine: self-hosted open-source Bolna at `~/Documents/mac/bolna_project`
- Local model: Qwen3.5-9B (4-bit) via `mlx_lm.server`, OpenAI-compatible, port 8080
- Python 3.12 via `uv`

## How to work with me (I am learning)
- Small steps. One milestone at a time. Never build ahead.
- Use plan mode for anything bigger than one file and show me the plan first.
- After every change, … *(the brief was cut off here: rest to be added)*

## Engineering rules
*(Not received yet: the brief was cut off before this section. To be added.)*
