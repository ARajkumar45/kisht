# Eval summary (local-qwen3.5-9b-v2)

agent `local:mlx-community/Qwen3.5-9B-4bit`, simulator `local:mlx-community/Qwen3.5-9B-4bit`; 40 personas, 160 runs, k=4

**pass^1 = 0.67**, **pass^4 = 0.38**, median turn 15.5 s, errors 0

| Category | Personas | pass^1 | pass^4 |
|---|---|---|---|
| adversarial | 5 | 0.95 | 0.80 |
| dispute | 2 | 0.38 | 0.00 |
| hardship | 4 | 0.69 | 0.25 |
| identity | 3 | 0.67 | 0.67 |
| negotiate | 6 | 0.71 | 0.33 |
| opt_out | 2 | 0.88 | 0.50 |
| pay_now | 3 | 1.00 | 1.00 |
| promise | 8 | 0.62 | 0.25 |
| terms | 4 | 0.31 | 0.00 |
| waiver | 3 | 0.42 | 0.00 |

Failed checks: {'promise': 22, 'followup': 2, 'escalate': 21, 'opt_out': 1, 'cites': 9, 'link': 1}
Guard blocks: {'false_claim_blocked': 86, 'date_out_of_policy': 14, 'leak_blocked': 12, 'amount_out_of_policy': 7, 'promise_exists': 1, 'bad_followup_date': 1, 'identity_mismatch': 8, 'banned_phrase': 10}
Replies replaced by code: {'unbacked_link_claim': 19, 'false_promise_claim': 57, 'leak_before_identity': 12, 'false_claim': 10, 'banned_phrase': 10}
