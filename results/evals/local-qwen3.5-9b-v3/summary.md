# Eval summary (local-qwen3.5-9b-v3)

agent `local:mlx-community/Qwen3.5-9B-4bit`, simulator `local:mlx-community/Qwen3.5-9B-4bit`; 40 personas, 160 runs, k=4

**pass^1 = 0.51**, **pass^4 = 0.15**, median turn 12.5 s, errors 0

| Category | Personas | pass^1 | pass^4 |
|---|---|---|---|
| adversarial | 5 | 0.85 | 0.60 |
| dispute | 2 | 0.38 | 0.00 |
| hardship | 4 | 0.31 | 0.00 |
| identity | 3 | 0.58 | 0.33 |
| negotiate | 6 | 0.71 | 0.17 |
| opt_out | 2 | 0.25 | 0.00 |
| pay_now | 3 | 0.83 | 0.33 |
| promise | 8 | 0.47 | 0.00 |
| terms | 4 | 0.06 | 0.00 |
| waiver | 3 | 0.42 | 0.00 |

Failed checks: {'no_promise': 5, 'link': 1, 'promise': 33, 'followup': 1, 'escalate': 27, 'nothing_revealed': 1, 'opt_out': 6, 'cites': 14}
Guard blocks: {'leak_blocked': 19, 'false_claim_blocked': 54, 'identity_not_verified': 3, 'date_out_of_policy': 8, 'amount_out_of_policy': 3, 'identity_mismatch': 11, 'identity_locked': 3, 'banned_phrase': 13}
Replies replaced by code: {'guessed_identity': 14, 'false_claim': 8, 'unbacked_link_claim': 32, 'false_promise_claim': 14, 'leak_before_identity': 5, 'banned_phrase': 13}
