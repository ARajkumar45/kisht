# Eval summary (ab-long-chat-v1)

agent `local:mlx-community/Qwen3.5-9B-4bit`, simulator `local:mlx-community/Qwen3.5-9B-4bit`; 10 personas, 40 runs, k=4

**pass^1 = 0.35**, **pass^4 = 0.20**, median turn 23.1 s, errors 0

| Category | Personas | pass^1 | pass^4 |
|---|---|---|---|
| hardship | 4 | 0.38 | 0.25 |
| opt_out | 2 | 0.88 | 0.50 |
| terms | 4 | 0.06 | 0.00 |

Failed checks: {'no_promise': 2, 'escalate': 10, 'opt_out': 1, 'promise': 6, 'cites': 13, 'link': 1}
Guard blocks: {'false_claim_blocked': 25, 'date_out_of_policy': 1, 'leak_blocked': 4, 'amount_out_of_policy': 1}
Replies replaced by code: {'false_promise_claim': 22, 'unbacked_link_claim': 3, 'guessed_identity': 2, 'leak_before_identity': 2}
