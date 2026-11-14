# Eval summary (heldout-qwen3.5-9b-v1)

agent `local:mlx-community/Qwen3.5-9B-4bit`, simulator `local:mlx-community/Qwen3.5-9B-4bit`; 20 personas, 40 runs, k=2

**pass^1 = 0.62**, **pass^2 = 0.45**, median turn 20.9 s, errors 0

pass^1 95% interval 0.47 to 0.78 (whole personas resampled). **Clean = 0.42**: passed, and at most one reply replaced by code, no reply in the wrong language, no repeated reply, not cut off by the turn limit.

| Category | Personas | pass^1 | pass^2 |
|---|---|---|---|
| adversarial | 2 | 1.00 | 1.00 |
| dispute | 2 | 0.25 | 0.00 |
| hardship | 2 | 0.50 | 0.00 |
| identity | 2 | 1.00 | 1.00 |
| negotiate | 2 | 0.75 | 0.50 |
| opt_out | 2 | 0.50 | 0.00 |
| pay_now | 2 | 1.00 | 1.00 |
| promise | 2 | 0.75 | 0.50 |
| terms | 2 | 0.50 | 0.50 |
| waiver | 2 | 0.00 | 0.00 |

Failed checks: {'promise': 3, 'escalate': 9, 'cites': 2, 'opt_out': 2}
Failed quality checks: {'not_cut_off': 13, 'few_safe_lines': 5, 'no_repeated_reply': 8}
Guard blocks: {'false_claim_blocked': 19, 'identity_mismatch': 2, 'leak_blocked': 5}
Replies replaced by code: {'false_claim': 7, 'false_promise_claim': 5, 'leak_before_identity': 3, 'unbacked_link_claim': 7, 'guessed_identity': 2}
