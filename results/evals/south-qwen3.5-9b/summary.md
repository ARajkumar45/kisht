# Eval summary (south-qwen3.5-9b)

agent `local:mlx-community/Qwen3.5-9B-4bit`, simulator `local:mlx-community/Qwen3.5-9B-4bit`; 8 personas, 16 runs, k=2

**pass^1 = 0.50**, **pass^2 = 0.38**, median turn 20.2 s, errors 0

| Category | Personas | pass^1 | pass^2 |
|---|---|---|---|
| south | 8 | 0.50 | 0.38 |

Failed checks: {'promise': 3, 'escalate': 4, 'opt_out': 1}
Guard blocks: {'false_claim_blocked': 1}
Replies replaced by code: {'unbacked_link_claim': 1}
