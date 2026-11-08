# Decisions — AI Receptionist

One line per decision. Rewritten 2026-11-08 from the new project brief, which replaces
the earlier D1–D42 list and docs/PLAN.md (both kept in git history). Some items from the
earlier list were kept on purpose and are marked *(kept)*.
To change a decision: edit its line, add the date and the reason.

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

## Open questions
- O1. Which business is the first customer (clinic, salon, or PG)?
- O2. Which languages do that business's callers actually use?
- O3. Which cloud model API for the pilot, and which cloud server and region?
- O4. Exact DPDP Act requirements (notice wording, consent, retention, processors) — check before the pilot.
- O5. Indian number for the pilot: Exotel or Plivo, and whose KYC?
- O6. Does Bolna hold up under load, or do we switch to Pipecat / LiveKit Agents?
- O7. Rest of "How to work with me" and the "Engineering rules": the brief was cut off; needed to finish CLAUDE.md.
- O8. Public GitHub repo after gate 1? (Was decided yes before the rewrite; reconfirm.)
