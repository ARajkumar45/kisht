# Eval summary (heldout-qwen3.5-9b-v2)

agent `local:mlx-community/Qwen3.5-9B-4bit`, simulator `local:mlx-community/Qwen3.5-9B-4bit`; 20 personas, 40 runs, k=2

**pass^1 = 0.60**, **pass^2 = 0.45**, median turn 21.0 s, errors 0

pass^1 95% interval 0.42 to 0.78 (whole personas resampled). **Clean = 0.47**: passed, and at most one reply replaced by code, no reply in the wrong language, no repeated reply, not cut off by the turn limit.

| Category | Personas | pass^1 | pass^2 |
|---|---|---|---|
| adversarial | 2 | 1.00 | 1.00 |
| dispute | 2 | 0.00 | 0.00 |
| hardship | 2 | 0.25 | 0.00 |
| identity | 2 | 1.00 | 1.00 |
| negotiate | 2 | 0.50 | 0.00 |
| opt_out | 2 | 1.00 | 1.00 |
| pay_now | 2 | 1.00 | 1.00 |
| promise | 2 | 0.75 | 0.50 |
| terms | 2 | 0.25 | 0.00 |
| waiver | 2 | 0.25 | 0.00 |

Failed checks: {'promise': 4, 'escalate': 10, 'cites': 3}
Failed quality checks: {'few_safe_lines': 6, 'no_repeated_reply': 3, 'not_cut_off': 5, 'right_language': 1}
Guard blocks: {'false_claim_blocked': 16, 'date_out_of_policy': 1, 'bad_reason': 1, 'leak_blocked': 6}
Replies replaced by code: {'false_promise_claim': 4, 'leak_before_identity': 4, 'false_claim': 6, 'unbacked_link_claim': 5, 'guessed_identity': 2, 'unbacked_handoff_claim': 1}
