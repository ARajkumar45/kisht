# Eval summary (south-qwen3.5-9b-v9)

agent `local:mlx-community/Qwen3.5-9B-4bit`, simulator `local:mlx-community/Qwen3.5-9B-4bit`; 8 personas, 16 runs, k=2

**pass^1 = 0.56**, **pass^2 = 0.38**, median turn 43.5 s, errors 0

pass^1 95% interval 0.31 to 0.81 (whole personas resampled). **Clean = 0.44**: passed, and at most one reply replaced by code, no reply in the wrong language, no repeated reply, not cut off by the turn limit.

| Category | Personas | pass^1 | pass^2 |
|---|---|---|---|
| south | 8 | 0.56 | 0.38 |

Failed checks: {'promise': 3, 'escalate': 3, 'opt_out': 1, 'no_promise': 1}
Failed quality checks: {'not_cut_off': 4, 'no_repeated_reply': 3, 'few_safe_lines': 2}
Guard blocks: {'date_out_of_policy': 2, 'false_claim_blocked': 11}
Replies replaced by code: {'unbacked_link_claim': 9, 'false_promise_claim': 1, 'false_claim': 1}
