# Zendesk Implementation Engine

A local web app for Nagarro Zendesk consultants: connect to a customer's Zendesk Support
instance, read and review its configuration, enter the customer's requirements, and let
the engine apply the changes (sandbox first).

**Status: Phase 2 (Config explorer).** The app reads all 21 Zendesk Support configuration
areas into a local snapshot, shows a coverage report, and lets you explore it: where each
field, group, brand, form, status, webhook, tag and more is used, what every rule uses,
unused custom fields and references to items that no longer exist, a comparison of any two
reads, and a current-state report for the customer (Word, or print to PDF). Plan:
[Development action plan](https://claude.ai/artifact/NUxKdHWUHvLPufZRZCmmho).

---

## 1. Prerequisites (once per laptop)

- Windows 10 or 11
- [Python 3.12 or newer](https://www.python.org/downloads/) (tick "Add python.exe to PATH")
- [Node.js 20 LTS or newer](https://nodejs.org)
- Admin access to the target Zendesk instance (dev: `pdi-nagarro6612.zendesk.com`)

## 2. Prepare the Zendesk instance (once per instance)

The engine signs in with an **OAuth client** (Zendesk stopped issuing new API tokens on
27 Oct 2026; existing ones stop working on 30 Apr 2027). Requests act as the user who
created the OAuth client, so create it from a dedicated service account:

1. **Create a service-account admin.** Admin Center → People → Team → Team members → Add user.
   Name it e.g. *ZIE Service*, use a mailbox you control, role **Admin**. Activate it and
   sign in as that user.
2. **Create the OAuth client** (signed in as the service account). Admin Center → Apps and
   integrations → APIs → OAuth clients → Add OAuth client:
   - Name: *Zendesk Implementation Engine*
   - Identifier: e.g. `zie-engine`
   - Client kind: **Confidential**
   - Allowed scopes: `read` for now (add `write` in Phase 4, when the engine starts applying
     changes)
3. **Save and copy the secret.** Zendesk shows it only once. Keep it in your password
   manager; you will paste it into the app's connect screen.

## 3. Install

From the repo root in PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
```

This creates `backend\.venv`, installs the Python packages and installs the UI packages.
Run it again whenever a phase adds packages (Phase 2 adds `python-docx` for the Word report).

## 4. Run

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start.ps1
```

Two windows open (backend on `127.0.0.1:8000`, UI on `127.0.0.1:5173`) and the browser
opens the app. On the connect screen:

1. Subdomain: `pdi-nagarro6612`
2. OAuth client identifier and secret from step 2
3. **Test connection** → it should say *acting as ZIE Service (admin)*
4. **Connect**, then on **Overview** click **Read everything**. The coverage table shows, for
   each area, whether it was read, how many items it has, and why if it is not available on
   the account's plan.
5. Open any area from the menu. The **Used by** column and the **Unused only** switch show
   what refers to each field, group, form and so on. Click a row for its panel: **Used by**,
   **Uses** (with missing items flagged) and the raw **JSON**; click any name to jump to it.
6. **Overview → Findings** lists unused custom ticket fields and references to missing items.
   **Report (Word)** downloads the current-state report; **Report (print / PDF)** opens a
   printable version (use the browser's Save as PDF).
7. **Explore → Tags** shows every tag the configuration sets, checks or offers through
   dropdowns. **Explore → History and compare** compares any two reads.

To stop, close the two PowerShell windows. **Disconnect** in the app removes the stored
credentials from Windows Credential Manager.

## 5. Command line (optional)

The `zie` CLI uses the same engine. It reads credentials from `backend\.env`
(`ZIE_SUBDOMAIN`, `ZIE_CLIENT_ID`, `ZIE_CLIENT_SECRET`) or, if those are empty, from the
connection you saved in the app.

```powershell
cd backend
.venv\Scripts\python -m zie auth test          # who the engine acts as
.venv\Scripts\python -m zie snapshot           # read every area, save a snapshot, print coverage
.venv\Scripts\python -m zie snapshot macros    # one area, live, as YAML (--format json)
.venv\Scripts\python -m zie serve              # API + built UI on 127.0.0.1:8000
```

## 6. Checks

```powershell
powershell -ExecutionPolicy Bypass -File scripts\check.ps1
```

Runs ruff, mypy (strict) and pytest for the backend, then the UI type check and production
build. Tests never call a real Zendesk instance.

## Project layout

```text
backend/                 Python 3.12+ engine and FastAPI backend
  src/zie/zendesk/       OAuth/API-token auth, HTTP client (retries, pagination)
  src/zie/readers/       Registry of the 21 configuration areas + one generic reader
  src/zie/snapshot.py    Read everything, per-area coverage, local snapshot store
  src/zie/dependencies.py  Where-used index, broken references, unused fields, tags
  src/zie/compare.py     Differences between two snapshots
  src/zie/report.py      Current-state report (Word and printable HTML)
  src/zie/api/           HTTP API used by the UI (localhost only)
  src/zie/store.py       Credential store (Windows Credential Manager) + local app state
  src/zie/cli.py         `zie` command line
  tests/                 Unit and API tests with a fake Zendesk
frontend/                React + TypeScript (Vite) UI with Mantine components
docs/adr/                Architecture decision records
scripts/                 setup.ps1, start.ps1, check.ps1
docs/ci/                 CI workflow; move to .github/workflows/ when the repo is hosted
```

## Security notes

- The backend listens on `127.0.0.1` only and rejects requests addressed to other host
  names.
- Secrets live in Windows Credential Manager (via `keyring`), never in plain-text files,
  logs or browser storage, and are never sent back to the UI.
- Snapshots contain the customer's configuration. They are saved only on this computer, in
  `%LOCALAPPDATA%\zendesk-implementation-engine\snapshots\<subdomain>\`, never in the repo.
- The engine requests the `read` scope only. Write access is requested only for applying an
  approved plan (Phase 4).

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `pip install` or `npm install` times out | Behind the Nagarro proxy, set it first: `$env:HTTPS_PROXY = "http://<proxy>:<port>"` then rerun setup |
| "running scripts is disabled on this system" | Use the `powershell -ExecutionPolicy Bypass -File ...` form shown above |
| "Zendesk rejected the OAuth client ID or secret" | Re-copy the secret; check the client kind is Confidential |
| "The OAuth client is not allowed to request this scope" | Add `read` to the client's allowed scopes |
| Warning: connected as role `agent` | Recreate the OAuth client while signed in as an admin |
| "The local engine is not running" in the browser | The backend window was closed; run `scripts\start.ps1` again |
