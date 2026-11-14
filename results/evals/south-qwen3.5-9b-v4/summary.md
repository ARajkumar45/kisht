# Eval summary (south-qwen3.5-9b-v4)

agent `local:mlx-community/Qwen3.5-9B-4bit`, simulator `local:mlx-community/Qwen3.5-9B-4bit`; 8 personas, 16 runs, k=2

**pass^1 = 0.38**, **pass^2 = 0.25**, median turn 12.6 s, errors 0

| Category | Personas | pass^1 | pass^2 |
|---|---|---|---|
| south | 8 | 0.38 | 0.25 |

Failed checks: {'promise': 4, 'escalate': 4, 'opt_out': 1, 'link': 1}
Guard blocks: {'false_claim_blocked': 4, 'bad_reason': 1, 'missing_fact': 1}
Replies replaced by code: {'false_claim': 2, 'false_promise_claim': 1, 'unbacked_link_claim': 1}
