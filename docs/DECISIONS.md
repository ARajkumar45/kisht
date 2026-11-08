# Decisions — AI Receptionist

Decided on 2026-11-08 in a design interview before any code was written.
There was no prior plan (no CLAUDE.md existed); these decisions are the plan.
Change a decision by editing it here and noting the date and reason.

## 1. Goal

- **D1. Primary goal:** a production-grade portfolio project that demonstrates FDE / AI engineering skill to hiring managers. A paying customer is secondary.

## 2. Customer and problem

- **D2. Domain:** healthcare — the front desk of a multi-doctor clinic in India. (Banking was rejected: little useful work possible without KYC/authentication, plus RBI and fraud risk.)
- **D3. Customer:** a realistic fictional clinic (e.g. "Sunrise Multispeciality Clinic") with fake doctors, schedules and patients for gates 1–2. Try to land a real clinic for the gate 3 pilot.
- **D4. City:** Bengaluru.
- **D5. Problem:** during the morning rush and after hours, clinic calls go unanswered and those callers book elsewhere. The agent answers, books into the clinic's schedule, and handles common questions (doctor availability, timings, fees, location).

## 3. Success numbers

- **D6. Headline success number (gate 3, real clinic):** ≥ 80% of calls the agent answers end in a correct booking or a clean handoff to staff. Also report how many staff-missed calls became bookings.
- **D7. Bar to pass gates 1–2 (test suite):** ≥ 90% of 50+ scripted test calls end correctly (right booking, right answer, or right handoff), with **zero** dangerous failures: no medical advice, no missed emergency, no double-booked slot.
- **D8. Production-grade bar ("done"):**
  - automated suite of 50+ scripted calls, run on every code change (CI)
  - per-call traces: transcript, tool calls, timing of each step
  - measured latency: median reply < 1.2 s, slowest 5% < 2.5 s
  - guardrails: no medical advice, human handoff, emergency detection
  - cost-per-call dashboard
  - one-command deploy
  - README covering architecture and trade-offs

## 4. Budget and spending gates

- **D9. Free and trial first.** Money is spent only at three gates:
  1. **Demo works:** ₹0. Local model, text simulator, microphone testing, existing Deepgram credit, Twilio trial for a few test calls, Mac as host.
  2. **Friends test by phone:** small top-up plus a rented number. Top-ups are fine when they clearly improve the result.
  3. **Real clinic pilot:** cheap cloud server plus credit, **capped at ₹3,000/month**.
- **D10. Hitting the cap (gate 3):** alert at 80% of the monthly cap; at 100%, calls fall back to the clinic's normal ringing or voicemail. The line never goes dead.
- **D11. Swappable parts:** the model, speech-to-text, text-to-speech and telephony each sit behind an adapter, so any paid part can be replaced with a cheaper one later.

## 5. Stack

- **D12. Model:** local Qwen 7–8B (4-bit) under an MLX server on the Mac, the largest size that keeps first spoken words under about 1 s. At gate 3, swap to a cheap hosted model if the cloud server can't run it.
- **D13. Speech-to-text:** Deepgram, using existing credit.
- **D14. Voice (text-to-speech):** Kokoro locally for development; Sarvam Bulbul for real calls (built for Indian voices and Hindi/English mixing, cheap); ElevenLabs as the premium swap. Choose voices that can be tuned so they don't sound robotic.
- **D15. Hosting:** the Mac for gates 1–2; a cheap cloud server for gate 3.

## 6. How people reach the agent

- **D16. In this order:**
  1. a browser "call the agent" link on a demo page (WebRTC). Free, and the main recruiter demo.
  2. an upgraded Twilio number (about $1–2/month, removes the trial message) at gate 2 for real phone calls; the Twilio trial covers the first 2–3 test calls.
  3. an Indian number (Exotel / Plivo / similar) at gate 3, registered under the real clinic's name (needs business KYC).

## 7. Scale

- **D17. Pilot:** 1 clinic, about 50 calls/day, at most 2 simultaneous calls. Build for this.
- **D18. Later:** 10 clinics, about 20 simultaneous calls. Keep each clinic's setup and data separate from day one, and include a load test that shows where the system breaks.

## 8. Languages

- **D19. v1:** English, Hindi, and Hinglish (switching within a sentence).
- **D20. After gate 2:** add Kannada as the third language (the clinic is in Bengaluru).

## 9. Privacy and consent (India DPDP Act 2023)

- **D21. Disclosure:** within the first 5 seconds the agent says it is an AI assistant and that the call is recorded to book appointments. Callers can say "staff" at any time to reach a person.
- **D22. Recording objection:** if the caller objects, the call continues unrecorded and only the booking is saved.
- **D23. Collect only what's needed:** name, phone number, preferred doctor and time, and a short visit reason ("fever", "follow-up"). No detailed symptoms.
- **D24. Personal details** are hidden in logs and traces.
- **D25. Retention:** recordings and transcripts are deleted after 30 days; bookings are kept.
- **D26. Data location:** at gates 1–2 the model runs locally, but Deepgram and Sarvam are cloud services, so audio leaves the device. At gate 3, host in an India region and use test data only until the clinic signs a data agreement. Provide a "delete my data" request path.

## 10. Medical safety

- **D27. No medical advice:** the agent never diagnoses or advises.
- **D28. Emergencies:** a fixed keyword-and-rule check in Hindi and English runs every turn, alongside the model, not relying on the model to notice. Signs include chest pain, breathlessness, heavy bleeding, unconsciousness, and suicidal thoughts. On a match the agent tells the caller to dial 108/112 and alerts the clinic.

## 11. When the agent is wrong

- **D29. Not understanding:** after 2 failed attempts it offers a transfer or a staff callback.
- **D30. Wrong booking:** it reads back doctor, date and time and waits for an explicit "yes". A WhatsApp/SMS confirmation is sent, and staff get a simple dashboard to fix or cancel bookings.
- **D31. Invented facts:** it answers only from the clinic's data (doctors, timings, fees) through tool calls. If the information isn't there, it says staff will confirm and never guesses.
- **D32. System down or over budget:** calls fall back to normal ringing or voicemail.
- **D33. Learning loop:** every mistake found in a trace becomes a new test call in the suite, so the same mistake can't return unnoticed.

## 12. Team

- **D34. Builder and operator:** built and run solo.
