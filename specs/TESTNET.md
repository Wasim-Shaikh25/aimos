# TESTNET — validate the live path against a real exchange, for free

**Objective:** confirm AIMOS's real account + order path actually works against a
live exchange **before risking any money** — using Binance's testnet, which speaks
the real API but trades with fake funds. This is go-live gate 3 (§23.8), and the
safe answer to "is the development really wired, or just mocked?"

The live code (`LiveBroker`, `MultiVenueLiveRouter`, preflight, mandate gate) is
mock-tested in CI. This runs it for real, end to end, with no capital at risk.

> Paper trading and price monitoring need **no keys at all**. You only need testnet
> keys to exercise the *account + order* path.

---

## 1. Get Binance testnet keys (5 minutes, free)

Binance runs two independent testnets — use **Spot**:

1. Go to **https://testnet.binance.vision/**.
2. Click **Log in with GitHub** (the testnet uses GitHub SSO; no KYC, no funds).
3. On the dashboard, click **Generate HMAC_SHA256 Key**.
4. Copy the **API Key** and **Secret Key** immediately — the secret is shown once.
5. The account is pre-funded with fake USDT/BTC. Nothing here touches real money.

Testnet base URL is `https://testnet.binance.vision/api` — the code selects it
automatically when `testnet=True` (the CLI default), so you don't set it by hand.

> Futures testnet (`https://testnet.binancefuture.com/`) exists too, but AIMOS's
> paper/live path is spot-first — use the Spot testnet above.

---

## 2. Give the keys to AIMOS (never in git, never logged)

Two ways — pick one. Keys are used **only** for the account/order path, never for
market-data analysis (§2), and are never journaled or shown in the UI.

**A. Secrets file (recommended).** Copy the template and fill it in:

```bash
cp secrets.example.yaml secrets.testnet.yaml
# edit secrets.testnet.yaml:
#   binance:
#     apiKey: "<testnet api key>"
#     secret: "<testnet secret>"
#     withdraw: false        # testnet keys can't withdraw anyway — keep it false
export AIMOS_SECRETS_FILE=$PWD/secrets.testnet.yaml
```

`secrets.*` is git-ignored (only `secrets.example.yaml` is tracked).

**B. Environment variables.** Per-venue, no file:

```bash
export AIMOS_KEY_BINANCE="<testnet api key>"
export AIMOS_SECRET_BINANCE="<testnet secret>"
```

---

## 3. Arm a tiny mandate

The validator refuses to place an order unless a mandate is enabled — the same
fail-closed gate the live path uses. In `config/mandate.yaml` set a small ceiling:

```yaml
enabled: true
max_total_notional_usdt: 50      # testnet money; keep it small anyway
max_positions: 1
allowed_quotes: [USDT]
```

(You can also override without editing the file:
`AIMOS__MANDATE__ENABLED=true`.)

Install the exchange client if you haven't: `pip install -e '.[data]'` (pulls
`ccxt`).

---

## 4. Run the validator

```bash
python -m scripts.validate_integration --exchange binance          # testnet (default)
```

It runs the full capability checklist against the real testnet API and prints a
PASS/FAIL report:

```
✅ authenticate + fetch balance: USDT free 10000.0
✅ withdrawals disabled (§23.4): key cannot withdraw
✅ place order: <order id>
✅ cancel + reconcile: {...}

ALL PASS (4/4)
```

- **authenticate + fetch balance** — read-only preflight: the key connects and
  can read the (fake) balance.
- **withdrawals disabled (§23.4)** — refuses any key that can withdraw. Testnet
  keys can't, so this passes; on mainnet it's your safety net.
- **place order → cancel + reconcile** — a tiny order is placed, cancelled, and
  reconciled against the journal. Nothing is left resting.

On an **all-pass**, the go-live ladder's *testnet* gate is marked and its 1-week
clock starts (see the **Go-Live** dashboard screen, or `/api/golive`).

Flags: `--symbol BTC/USDT` (default), `--notional 11` (order size in USDT; keep it
above the exchange minimum, ~$10 for BTC/USDT).

---

## 5. (Optional) let the serve loop use the keys

Once keys are configured, starting the server (`python -m aimos.runtime.serve`)
runs the read-only **preflight** on boot: the **Connections** and **Balances**
screens then show live testnet balances instead of the simulated sheet. Still no
orders are placed by the loop — paper stays paper until the go-live ladder is
complete.

---

## 6. Going to mainnet (real money) — deliberately harder

`--mainnet` runs the exact same checklist against the real exchange with a real
(tiny) order and a 5-second abort window:

```bash
python -m scripts.validate_integration --exchange binance --mainnet
```

This still is **not** live trading — it's a one-shot integration check. Real live
trading additionally requires every §23.8 go-live gate signed off (the boot guard
refuses `mode: live` otherwise) and funded, **withdrawal-disabled** keys. See
`specs/OPERATIONS.md` (go-live ladder) and the **Go-Live** dashboard screen.

---

## What "PASS" proves — and doesn't

**Proves:** the account path authenticates, reads balances, enforces the
withdrawal-disabled safety gate, and can place/cancel/reconcile a real order
against a real matching engine. The build is genuinely wired, not just mocked.

**Doesn't prove:** profitability, fill quality under load, or multi-venue arb
economics with real inventory. Those come from the paper track and, later, a
capital-limited live pilot behind the full ladder.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `no keys for binance` | `AIMOS_SECRETS_FILE` not exported, or the venue key isn't in it. |
| `mandate not enabled` | set `enabled: true` in `config/mandate.yaml` (step 3). |
| `ccxt`/import errors | `pip install -e '.[data]'`. |
| `withdrawals disabled … refused` | the key can withdraw — regenerate a trade-only key. |
| order rejected: min notional | raise `--notional` above the symbol's minimum (~$10). |

See `specs/OPERATIONS.md` for the full run/deploy reference and the go-live ladder.
