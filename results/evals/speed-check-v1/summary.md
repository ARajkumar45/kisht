# Eval summary (speed-check-v1)

agent `local:mlx-community/Qwen3.5-9B-4bit`, simulator `local:mlx-community/Qwen3.5-9B-4bit`; 14 personas, 28 runs, k=2

**pass^1 = 0.71**, **pass^2 = 0.64**, median turn 10.8 s, errors 0

| Category | Personas | pass^1 | pass^2 |
|---|---|---|---|
| identity | 3 | 0.67 | 0.67 |
| pay_now | 3 | 1.00 | 1.00 |
| promise | 8 | 0.62 | 0.50 |

Failed checks: {'promise': 6, 'escalate': 2}
Guard blocks: {'false_claim_blocked': 15, 'bad_reason': 1, 'leak_blocked': 6, 'date_out_of_policy': 1, 'identity_mismatch': 4}
Replies replaced by code: {'unbacked_link_claim': 9, 'false_claim': 2, 'false_promise_claim': 4, 'guessed_identity': 4, 'leak_before_identity': 2}
