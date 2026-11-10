# Eval summary (smoke-v2)

agent `local:mlx-community/Qwen3.5-9B-4bit`, simulator `local:mlx-community/Qwen3.5-9B-4bit`; 3 personas, 3 runs, k=1

**pass^1 = 0.33**, **pass^1 = 0.33**, median turn 10.2 s, errors 0

| Category | Personas | pass^1 | pass^1 |
|---|---|---|---|
| hardship | 1 | 1.00 | 1.00 |
| identity | 1 | 0.00 | 0.00 |
| promise | 1 | 0.00 | 0.00 |

Failed checks: {'promise': 1, 'escalate': 1, 'nothing_revealed': 1}
Guard blocks: {'date_out_of_policy': 1}
Replies replaced by code: {}
