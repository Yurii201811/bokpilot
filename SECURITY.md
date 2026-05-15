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
- Local `data/workspace.json` files containing real information.

## Current security posture

Bokpilot is a local-first MVP. It has no authentication, no multi-user permission model, and no encrypted document store. Run it on a trusted machine and do not expose it directly to the public internet.

## Future security requirements

Before adding live integrations, the project should include:

- OAuth token storage guidance.
- Scoped permissions and draft-only defaults.
- Audit logs.
- Explicit human approval gates.
- Redaction in logs and issue templates.
- Threat model for document uploads and accounting-system writes.
