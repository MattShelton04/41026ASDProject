# Pre-commit security evidence (R2-30, R2-31)

| File | Contents | Produced by |
|---|---|---|
| `pre-commit-report.md` | The security testing report: summary, commit hooks, results by slice and owner, dependency audit, and how to reproduce | `uv run scripts/dev.py security report` |
| `ruff-security.json` | Every Ruff `S` finding with its slice, status and justification | same |
| `detect-secrets.json` | Every secret candidate compared with `.secrets.baseline` | same |
| `pip-audit.json` | Raw pip-audit output for the locked dependencies, with no ignores applied | same |
| `pre-commit-commit-run.txt` | Hook output from a real commit, showing the security hooks running | `uv run pre-commit run --hook-stage pre-commit --files <staged files>` |

Regenerate the report after any change to security findings, `.secrets.baseline`,
`scripts/security/accepted-risks.toml` or `uv.lock`. The report records the commit it scanned.

Each student finds their results under **Results by slice**. A `pending-owner` finding is the
owner's to fix in code, or to justify with `# noqa: CODE - reason` on the reported line. After that,
delete the file's entry from `[tool.ruff.lint.extend-per-file-ignores]` in the root
`pyproject.toml` and regenerate the report. The procedure is in
[CONTRIBUTING.md](../../../../CONTRIBUTING.md#security-scans).
