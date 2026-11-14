# Eval summary (south-qwen3.5-9b-v7)

agent `local:mlx-community/Qwen3.5-9B-4bit`, simulator `local:mlx-community/Qwen3.5-9B-4bit`; 8 personas, 16 runs, k=2

**pass^1 = 0.56**, **pass^2 = 0.38**, median turn 35.8 s, errors 0

pass^1 95% interval 0.31 to 0.81 (whole personas resampled). **Clean = 0.44**: passed, and at most one reply replaced by code, no reply in the wrong language, no repeated reply, not cut off by the turn limit.

| Category | Personas | pass^1 | pass^2 |
|---|---|---|---|
| south | 8 | 0.56 | 0.38 |

Failed checks: {'promise': 3, 'escalate': 3, 'no_promise': 1, 'opt_out': 1}
Failed quality checks: {'no_repeated_reply': 6, 'few_safe_lines': 2, 'not_cut_off': 5}
Guard blocks: {'false_claim_blocked': 10}
Replies replaced by code: {'unbacked_link_claim': 5, 'false_promise_claim': 5}
