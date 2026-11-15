# ADR 0009: tastytrade as a live, personal, read-only data source

**Status:** Accepted
**Date:** 2026-11-15
**Deciders:** Project owner
**Builds on:** [ADR 0008](0008-options-from-free-snapshots.md) (the options page on Yahoo's chains)

## Context

The options page runs on Yahoo's chains. They are about 15 minutes late, Yahoo throttles them, and they have no history: our own daily IV history began on 2026-11-13, so IV percentile reads "collecting" for months.

The owner has a funded tastytrade account and wants three things:
- real-time quotes;
- market history for study (IV rank and percentile, years of candles);
- their own trades analysed.

tastytrade's Open API is free to account holders. We read its docs and its Open API terms on 2026-11-15.

**What the API offers:**
- **Sign-in:** a personal OAuth app on the owner's own account. Its refresh token never expires, and buys 15-minute access tokens. Scopes are `read`, `trade` and `openid`; anything that changes state needs `trade`.
- **Chains and quotes:** option chains with each contract's symbols, and REST quotes (bid, ask, mark, volume, update time) for 100 symbols a call, real-time for funded accounts.
- **Market metrics:** IV index, rank and percentile, 30-day IV, historical volatility, per-expiry IVs, and the next earnings with before-the-open / after-the-close timing.
- **DXLink websocket (dxFeed):** candle history (with `impVolatility` and `openInterest` fields), Summary (open interest) and Greeks.
- **The owner's accounts:** transactions, positions and balance snapshots.
- **Not offered:** an IV time series endpoint.

**What the terms allow:**
- **§8(3):** use of the data "is limited to trading" and watchlist activity, and the agreement "does not permit for subscribing to large cross-sections of the market for data collection purposes".
- **§8(4) and §8(6):** no copying, showing or making it available to any third party, in any manner.
- **§8(10):** a figure computed from their data stays their data if theirs can be recalculated from it, or if it can stand in for theirs.
- **§8(11):** never public, including on any website.
- **§6(3)(f) and (g):** the software must be the owner's own, with no third-party "API Hub" in between.
- **The definition of "Data"** excludes data "relating solely and specifically to Transactions you have entered into with us". The owner's own trades are not restricted by these clauses.

## Options considered

### Option 1: Replace Yahoo with tastytrade everywhere
- Pros: one source; real-time; no Yahoo throttling.
- Cons:
  - the daily IV snapshot would become a stored collection of their data (§8(3), §8(10));
  - the cited AI read would send their figures to an LLM provider (§8(4));
  - the demo would show them publicly (§8(11));
  - the page would stop working without the owner's account.

### Option 2: Scrape a site that shows real-time chains (TradingView, OptionCharts)
- Pros: no account needed.
- Cons: their terms forbid it, and the project already refuses to disguise a client (CNN's fear & greed).

### Option 3 *(chosen)*: tastytrade as a live overlay, for the owner only
- Pros: real-time where it matters, within the terms; Yahoo's pipeline, the stored history and the AI read are unchanged.
- Cons:
  - two sources on one page;
  - tastytrade's history can be viewed but not kept;
  - a never-expiring brokerage credential now lives on Fly.

## Decision

1. **Live and personal.**
   - tastytrade data is fetched when the owner opens a page and cached briefly in memory.
   - No table stores it.
   - It never feeds the AI read or any prompt.
   - It never reaches `/demo`.
   - Our stored IV history stays Yahoo-based and ours.
2. **Claude Code sessions are third parties too.**
   - Probes and checks print metadata only: ages, counts, date ranges, field names, and yes/no comparisons computed in code.
   - The owner compares values in tastytrade's own app. `app/services/tastytrade_probe.py` is built that way, and a test feeds it distinctive values and fails if one reaches its report.
3. **Read only.**
   - Every token refresh asks for `scope=read`. An access token is used only when what it may do is known: `read`, perhaps `openid`, and one `accounts:<number>:<authority>` scope per account it reaches (tastytrade adds these; acting on an account still takes `trade`). Anything else is refused. The answer's `scope` field or the token's own claim says so, and either one saying `trade` is enough to refuse it.
   - A read-only access token doesn't make the stored refresh token read-only. The probe checks the grant itself: one sign-in that doesn't narrow the scope, its token dropped unused. If the grant can trade, the owner replaces it with a read-only one.
   - Apart from the sign-in POST, the client makes GET calls only, to paths on an allowlist with no order path.
   - Tests check the module's source for any other write call, and every request a session makes.
4. **The credential.**
   - The client ID, client secret and refresh token are Fly secrets; empty values turn tastytrade off.
   - They are never logged, and account numbers are masked in logs.
   - Every failed sign-in is remembered, so neither waiting callers nor later ones sign in again at once. Repeated failed logins block the server's IP for about 8 hours.
     - A refusal (a 4xx other than 429) pauses all calls for an hour.
     - Anything else pauses them for a minute, or for the server's Retry-After.
   - The API address is one of tastytrade's two, so a typo can't send the refresh token anywhere else.
   - If the token leaks, delete the grant on my.tastytrade.com and create a new one.
5. **DXLink connects only to tastytrade's feed hosts** (`tasty-openapi-ws.dxfeed.com`, named in the docs, and `tasty-openapi-dxlink-md-ws.dxfeed.com`, which the owner's account was given), over TLS on port 443.
   - The address arrives with the quote token. One with credentials, a query or a fragment in it is refused.
   - No redirect is followed.
   - Messages are capped at 4 MiB and not compressed, and a fetch keeps at most 100,000 events and 20,000 candles.
   - A server error is reported by its known code only.
6. **The owner's own trades** may be read and analysed. They still stay out of the database (at first) and out of any prompt.
7. **The order of work:**
   - **PR A:** connect, then probe what the account gets.
   - **PR B:** live quotes on the options page.
   - **PR C:** market history, live.
   - **PR D:** a trade journal.

   The probe's answers (real-time or not, candle depth, IV in candles, option candles) decide what B and C build.

## Consequences

- **The page shows two sources.** Every tastytrade figure is labelled as tastytrade's, with its age. Yahoo's stay labelled "15-minute delayed".
- **Study means viewing.** Multi-year history from tastytrade can be charted on demand but not kept. If the owner wants a stored tastytrade history, that needs tastytrade's permission first (api.support@tastytrade.com), and a new ADR.
- **The tastytrade credential lives on Fly only** (not GitHub, not a browser), and is revoked from tastytrade's grant list. A leak of the shared secret does not expose it: no route returns it.
- **Verification by Claude stays at the metadata level.** A check that needs tastytrade's values is the owner's to make.
- **Revisit when:** tastytrade's terms change, the owner wants stored history, or a second user arrives (a personal app serves only its owner's account).

## Amendment, 2026-11-15: an owner key, the owner's positions, and an encrypted copy of the trades

The owner asked for two things: a page of their open positions with analysis, and a copy of their trades that both of their PCs can reach. Decided with the owner:

1. **An owner key.** The owner's account data sits behind routes under `/v1/owner`, which need the shared secret and a second key, `X-Owner-Key` (`OWNER_KEY`, a Fly secret).
   - **Why:** the shared secret is also a GitHub Actions secret (the IV snapshot cron), so a leak there must not open the account.
   - **Fail closed:** with no owner key configured those routes don't exist (404), local dev included.
   - **Lockout:** an address that sends ten wrong keys in an hour is locked out, the right key included, until a try refills.
   - **Two PCs:** the owner keeps the key in a password manager that syncs it. The sign-in forms carry a fixed username so a manager can save them.
   - `tests/test_owner_auth.py` pins the owner's routes.
2. **Positions, live.** Open positions are read when the owner opens the page and are never stored. Their live marks, IVs and Greeks are tastytrade's data, so decision 1 applies to them. The analysis is computed in code, with no prompt.
   - **No list of holdings is left behind:** the page reads each underlying's option report with `track=false`, so the holdings aren't recorded as option-page views (which the daily run would then snapshot). The candle cache still keeps prices for any ticker read, held or not, as it always has.
   - **The key in the browser:** the owner chose a key each browser keeps until sign out, filled by a password manager. So it sits in `localStorage` beside the shared secret. One XSS, or a look at a shared PC's storage, gets both, which `sessionStorage` would not avoid against XSS anyway. It goes with the sign-in however that ends, a forced sign-out on a 401 included.
3. **Decision 6 changes for the trades.** The owner's transactions are their own (the terms' "Data" excludes them), so they may be kept.
   - **Where:** Neon, one row per transaction, encrypted (AES-256-GCM) with a key held as a Fly secret. Only the transaction id, the key version and an estimated-fee flag stay outside the ciphertext, and all three are bound to it.
   - **Still never stored:** tastytrade's market data.
   - **Still out of every prompt:** the trades themselves.
   - **Claude sessions:** a session checks counts only, never decrypting or printing a trade.

