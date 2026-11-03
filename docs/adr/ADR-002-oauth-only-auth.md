# ADR-002: OAuth client credentials by default; API tokens only as a fallback

- Status: Accepted
- Date: 2026-10-28

## Context

Zendesk is removing API tokens as an authentication method
([announcement](https://support.zendesk.com/hc/en-us/articles/10851263566234)):

- Accounts created from 28 Jul 2026 cannot use API tokens.
- New tokens cannot be created from 27 Oct 2026.
- All remaining tokens are deactivated on 30 Apr 2027.

The replacement for server-to-server access is the OAuth **client credentials** grant
([migration guide](https://developer.zendesk.com/documentation/authentication/oauth-migration/)):
a confidential OAuth client posts `grant_type=client_credentials` (form-encoded) to
`https://{subdomain}.zendesk.com/oauth/tokens` and receives a bearer token with an
`expires_in` (example: 1,800 s) and no refresh token. Requests act as the user who
created the OAuth client.

## Decision

- OAuth client credentials is the default and recommended connection type.
- Each customer instance gets a **dedicated service-account admin** that owns the OAuth
  client, so audit logs show the engine, not a person.
- The engine requests the narrowest scope: `read` to connect and explore; `read write`
  only for Plan & apply (Phase 4). If `scope` is omitted Zendesk grants read and write,
  so the engine always sends it explicitly.
- Tokens are cached in memory, renewed 60 s before expiry, and renewed once after a 401.
- Credentials are stored per subdomain in the OS credential store (Windows Credential
  Manager) via `keyring`; secrets are never written to disk in plain text or returned to
  the browser.
- API tokens (`{email}/token:{token}` Basic auth) remain as a clearly labelled fallback
  for older accounts until 30 Apr 2027.

## Consequences

- Setting up a customer instance needs one extra step (create the service account and the
  OAuth client); the README documents it.
- No token-based code needs rewriting before the April 2027 cut-off.
