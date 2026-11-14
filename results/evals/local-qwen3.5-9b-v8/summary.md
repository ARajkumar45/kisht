# Eval summary (local-qwen3.5-9b-v8)

agent `local:mlx-community/Qwen3.5-9B-4bit`, simulator `local:mlx-community/Qwen3.5-9B-4bit`; 40 personas, 160 runs, k=4

**pass^1 = 0.58**, **pass^4 = 0.33**, median turn 20.9 s, errors 0

pass^1 95% interval 0.47 to 0.69 (whole personas resampled). **Clean = 0.32**: passed, and at most one reply replaced by code, no reply in the wrong language, no repeated reply, not cut off by the turn limit.

| Category | Personas | pass^1 | pass^4 |
|---|---|---|---|
| adversarial | 5 | 0.85 | 0.80 |
| dispute | 2 | 0.62 | 0.50 |
| hardship | 4 | 0.44 | 0.25 |
| identity | 3 | 0.67 | 0.67 |
| negotiate | 6 | 0.42 | 0.00 |
| opt_out | 2 | 0.75 | 0.50 |
| pay_now | 3 | 0.83 | 0.33 |
| promise | 8 | 0.66 | 0.25 |
| terms | 4 | 0.38 | 0.25 |
| waiver | 3 | 0.25 | 0.00 |

Failed checks: {'no_promise': 3, 'link': 1, 'promise': 37, 'followup': 2, 'escalate': 25, 'opt_out': 2, 'cites': 4}
Failed quality checks: {'right_language': 6, 'not_cut_off': 54, 'no_repeated_reply': 21, 'few_safe_lines': 52}
Guard blocks: {'false_claim_blocked': 155, 'leak_blocked': 29, 'bad_followup_date': 1, 'date_out_of_policy': 9, 'amount_out_of_policy': 2, 'identity_not_verified': 2, 'identity_mismatch': 19, 'identity_locked': 2, 'bad_reason': 2, 'banned_phrase': 10}
Replies replaced by code: {'unbacked_link_claim': 48, 'false_claim': 22, 'false_promise_claim': 80, 'guessed_identity': 17, 'unbacked_handoff_claim': 5, 'leak_before_identity': 12, 'banned_phrase': 10}
