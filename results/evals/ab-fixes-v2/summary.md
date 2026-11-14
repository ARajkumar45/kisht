# Eval summary (ab-fixes-v2)

agent `local:mlx-community/Qwen3.5-9B-4bit`, simulator `local:mlx-community/Qwen3.5-9B-4bit`; 8 personas, 16 runs, k=2

**pass^1 = 0.44**, **pass^2 = 0.25**, median turn 23.2 s, errors 0

| Category | Personas | pass^1 | pass^2 |
|---|---|---|---|
| hardship | 4 | 0.25 | 0.00 |
| terms | 4 | 0.62 | 0.50 |

Failed checks: {'escalate': 6, 'promise': 2, 'cites': 2}
Guard blocks: {'false_claim_blocked': 16, 'amount_out_of_policy': 2, 'leak_blocked': 4}
Replies replaced by code: {'false_promise_claim': 5, 'false_claim': 1, 'unbacked_link_claim': 10, 'leak_before_identity': 4}
