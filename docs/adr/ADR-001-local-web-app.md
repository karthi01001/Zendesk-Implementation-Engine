# ADR-001: A local, single-user web app over one Python core

- Status: Accepted
- Date: 2026-10-28

## Context

Consultants need to connect to a customer's Zendesk instance, read its full configuration,
review it in a clean UI, enter the customer's requirements in that same UI, and have the
engine apply the resulting changes. The code lives on a consultant's laptop until the
product is hosted. Customer credentials and data must stay under tight control.

## Decision

- **Python 3.12+ core engine** (`backend/src/zie`): Zendesk client, readers, and later the
  blueprint model, planner and applier. All business logic lives here.
- **FastAPI backend** exposing the core to the UI over HTTP, bound to `127.0.0.1` only,
  with a trusted-host check against DNS-rebinding.
- **React + TypeScript (Vite) UI** using the Mantine component library. In development it
  runs on `127.0.0.1:5173` and proxies `/api` to the backend; a production build is served
  by the backend itself on `127.0.0.1:8000`.
- **`zie` CLI** on the same core for scripting and CI.
- **Single user, local first.** No login, tenancy or central vault until hosting.

## Consequences

- One codebase serves the UI, the CLI and, later, an MCP server for Claude.
- Each consultant installs Python and Node once (`scripts/setup.ps1`).
- Moving to a hosted, multi-user version later needs: sign-in, per-user credential
  storage in a vault, and multi-tenant project storage. The core engine does not change.
