# Eval summary (south-qwen3.5-9b-v2)

agent `local:mlx-community/Qwen3.5-9B-4bit`, simulator `local:mlx-community/Qwen3.5-9B-4bit`; 8 personas, 16 runs, k=2

**pass^1 = 0.56**, **pass^2 = 0.25**, median turn 21.7 s, errors 0

| Category | Personas | pass^1 | pass^2 |
|---|---|---|---|
| south | 8 | 0.56 | 0.25 |

Failed checks: {'promise': 3, 'no_promise': 1, 'escalate': 2, 'opt_out': 2}
Guard blocks: {'false_claim_blocked': 4, 'date_out_of_policy': 1}
Replies replaced by code: {'unbacked_link_claim': 3, 'false_claim': 1}
