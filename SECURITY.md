# Security policy

## Supported versions

The project is pre-1.0. Security fixes target the latest `main` branch until formal releases begin.

## Reporting a vulnerability

Please do not open a public issue for vulnerabilities that expose personal data, financial records, workspace files, or future integration credentials.

Report privately to the maintainers once a public contact is configured. Until then, create a minimal issue saying that a private security report is needed, without including secrets or sensitive files.

## Sensitive data

Do not commit:

- Real receipts or invoices.
- Bank exports.
- Personal identity data.
- Customer or supplier records.
- API keys, OAuth tokens, cookies, or `.env` files.
- Local SQLite databases, attachment directories, exports, or backup bundles containing real information.

## Current security posture

Bokpilot is a local-first application with no multi-user permission model and no encrypted document store. Run it on a trusted machine and do not expose it through a proxy or directly to the public internet.

The built-in server refuses non-loopback binds, validates the exact `Host` header to reduce DNS-rebinding risk, issues an in-memory startup session token, requires that token on mutations, checks any supplied `Origin`, accepts JSON mutation bodies only, and caps their declared size. These controls protect the local HTTP boundary; they are not remote-user authentication and do not make public deployment safe.

Review decisions and duplicate decisions are append-only audit records. Stale item versions are rejected. Reset requires explicit confirmation and creates a verified backup before clearing database records.

## Additional requirements before remote or multi-user use

Before adding live integrations, the project should include:

- OAuth token storage guidance.
- Scoped permissions and draft-only defaults.
- Audit logs.
- Explicit human approval gates.
- Redaction in logs and issue templates.
- Threat model for document uploads and accounting-system writes.
