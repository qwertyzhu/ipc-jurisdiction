# Security policy

## Supported versions

Only the latest commit on `main` receives fixes during the early preview.

## Reporting a vulnerability

Use [GitHub private vulnerability reporting](https://github.com/qwertyzhu/ipc-jurisdiction/security/advisories/new).

Do **not** attach real complaints, business-registration extracts, notarial certificates, client identities, or case numbers to a public issue.

## Data-handling boundary

- The engine is designed for **local** processing. It does not call the network and does not write case logs.
- Inputs should be province / city / district / amount / filing date — not a full case file.
- Repository fixtures are public rules and fictional examples. Do not replace them with live matter files.

## Accidental disclosure

If a live matter file is pushed:

1. rewrite git history (`git filter-repo`) only if you understand the impact;
2. contact GitHub Support for cached commit removal if needed;
3. follow your firm’s incident process for client data.
