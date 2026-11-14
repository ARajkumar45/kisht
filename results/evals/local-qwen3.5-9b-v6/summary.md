# Eval summary (local-qwen3.5-9b-v6)

agent `local:mlx-community/Qwen3.5-9B-4bit`, simulator `local:mlx-community/Qwen3.5-9B-4bit`; 40 personas, 160 runs, k=4

**pass^1 = 0.56**, **pass^4 = 0.25**, median turn 19.6 s, errors 0

pass^1 95% interval 0.45 to 0.66 (whole personas resampled). **Clean = 0.33**: passed, and at most one reply replaced by code, no reply in the wrong language, no repeated reply, not cut off by the turn limit.

| Category | Personas | pass^1 | pass^4 |
|---|---|---|---|
| adversarial | 5 | 0.95 | 0.80 |
| dispute | 2 | 0.50 | 0.50 |
| hardship | 4 | 0.31 | 0.00 |
| identity | 3 | 0.67 | 0.67 |
| negotiate | 6 | 0.38 | 0.00 |
| opt_out | 2 | 0.88 | 0.50 |
| pay_now | 3 | 0.92 | 0.67 |
| promise | 8 | 0.47 | 0.00 |
| terms | 4 | 0.31 | 0.00 |
| waiver | 3 | 0.50 | 0.00 |

Failed checks: {'link': 1, 'promise': 36, 'followup': 4, 'escalate': 25, 'no_promise': 2, 'opt_out': 1, 'cites': 10}
Failed quality checks: {'not_cut_off': 46, 'few_safe_lines': 48, 'no_repeated_reply': 30, 'right_language': 3}
Guard blocks: {'false_claim_blocked': 142, 'leak_blocked': 23, 'date_out_of_policy': 6, 'amount_out_of_policy': 3, 'date_in_past': 1, 'identity_not_verified': 2, 'identity_mismatch': 16, 'identity_locked': 4, 'banned_phrase': 21}
Replies replaced by code: {'unbacked_link_claim': 58, 'false_claim': 9, 'leak_before_identity': 15, 'false_promise_claim': 68, 'guessed_identity': 8, 'unbacked_handoff_claim': 6, 'unbacked_optout_claim': 1, 'banned_phrase': 21}
