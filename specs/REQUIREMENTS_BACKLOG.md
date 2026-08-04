# Requirements Backlog

Historical backlog items have been folded into `CHANGELOG.md` and `specs/STATUS.md`
as they shipped. The multi-tenant/SaaS control-plane items are obsolete after the
single-user refactor and have been removed from the codebase. Active remaining work
is tracked in `specs/STATUS.md`.

---

## New / unscheduled items

### REQ-20: Guided UI to connect Binance and other exchange platforms

- **Source:** direct operator request.
- **Evidence — the form is a raw text box, not a picker.**
  `dashboard/src/screens/Settings.jsx:44,177` — the "Add exchange key" form's
  `Venue` field is a free-text `Field` component defaulting to the string
  `"binance"`, with no dropdown, no list of what's actually supported, and no
  per-exchange guidance (testnet URL, where to generate a read-only key, etc.).
  It posts straight to `POST /api/v2/settings/exchange`
  (`aimos/saas/router.py:184-191`), which encrypts and stores whatever string is
  typed with **zero validation that the venue or the key is even valid**.
- **Evidence — two disconnected credential stores.** Exchange keys added through
  the Settings UI are written to `SettingsStore` (Fernet-encrypted,
  `aimos/saas/settings_store.py`) and that store **is** what live multi-venue
  execution reads (`aimos/runtime/serve.py:652-659`,
  `store.get_exchange_credentials(venue)`). But the read-only preflight
  self-check that powers the **Connections screen** — the only place an operator
  can see "does this key actually connect, is withdrawal disabled, what's the
  balance" — reads from a completely different, legacy source:
  `aimos/runtime/serve.py:773-783`, `_run_preflight()` calls
  `aimos.account.secrets.load_secrets(secrets_file, venues=venues)`, i.e.
  `secrets.yaml` / `AIMOS_KEY_<VENUE>` env vars, computed **once at boot**. It
  never looks at `SettingsStore`. `dashboard/src/screens/Connections.jsx:17-20`
  confirms this in its own copy: *"Add them via `AIMOS_SECRETS_FILE`... or env
  vars, then restart"* — it doesn't mention the Settings UI path at all, because
  from the preflight's point of view that path doesn't exist.
  **Net effect:** an operator who adds a Binance key through Settings gets no
  feedback whatsoever — no connection test, no balance, no withdrawal-disabled
  check — unless they *also* separately populate `secrets.yaml` and restart the
  process. The two systems don't talk to each other.
- **Evidence — supported venues aren't surfaced.** `config/default.yaml:18-19`
  configures `primary: binance`, `secondary: [bybit, kraken]`; other screens
  reference `coinbase` as well. ccxt (already a dependency) technically supports
  100+ exchanges by `exchange_id` string, but nothing in the UI tells the
  operator which ones AIMOS actually exercises/tests against versus which are
  theoretically reachable through ccxt but unvalidated.
- **Rationale:** this is exactly the gap between "a key-value store with a lock"
  and "a connect-your-exchange feature." An operator adding Binance today has no
  way to know, from the UI, whether they typed the right `exchange_id`, whether
  the key actually authenticates, or whether it's withdrawal-enabled (the one
  thing that must never be true) — until they dig into a separate screen backed
  by a separate, file-based configuration path they may not even know exists.
- **Acceptance criteria:**
  1. Replace the free-text `Venue` field with a picker of supported venues
     (binance, kraken, bybit, coinbase — matching `config/default.yaml`'s
     configured set) plus an explicit "Other (advanced: raw ccxt exchange ID)"
     option for anything ccxt supports beyond the curated list.
  2. Add a **"Test connection"** step at add-time: a new endpoint (e.g.
     `POST /api/v2/settings/exchange/test`) that runs the existing
     `aimos.account.preflight.preflight_check` logic against the
     just-submitted credentials *before* they're persisted, and returns
     connected/can-trade/withdrawal-disabled/balance/error — so the operator
     gets immediate feedback instead of silent encrypted storage. Never echoes
     the key/secret back (same redaction rule as `get_exchanges()`).
  3. Point the Connections preflight (`_run_preflight` in `serve.py`) at
     `SettingsStore.get_exchange_credentials()` as its source of truth — or
     explicitly merge both sources — so a key added via the UI is reflected on
     the Connections screen without a restart, closing the split described
     above. Update `Connections.jsx`'s copy to match (it currently sends
     operators toward a config path this makes secondary).
  4. Per-venue setup guidance in the UI (where to generate a **read-only,
     withdrawal-disabled** key on that exchange — the one operational
     requirement the whole live-trading safety model depends on).
  5. Tests: an API test for the new test-connection endpoint (success, bad
     creds, unknown venue); a test that adding a key via `SettingsStore` is
     visible to `_run_preflight`/the Connections payload.
- **Priority:** High (direct operator request; closes a real, evidenced gap
  between two systems that should be one). **Effort:** Medium — no new
  external integration, this wires up preflight logic and UI that already
  exist; the picker and the merge-credential-sources step are the real work.
- **Dependencies:** none — builds entirely on existing
  `aimos/account/preflight.py`, `SettingsStore`, and the multi-venue live path.

