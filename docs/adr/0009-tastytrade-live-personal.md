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
   - Every token refresh asks for `scope=read`, and an access token that comes back able to trade is refused.
   - Apart from the sign-in POST, the client makes GET calls only, to paths on an allowlist with no order path.
   - Tests check the module's source for any other write call, and every request a session makes.
4. **The credential.**
   - The client ID, client secret and refresh token are Fly secrets; empty values turn tastytrade off.
   - They are never logged, and account numbers are masked in logs.
   - A refused sign-in pauses all calls for an hour, since repeated failed logins block the server's IP for about 8 hours.
   - If the token leaks, delete the grant on my.tastytrade.com and create a new one.
5. **DXLink connects only to a dxFeed websocket over TLS.** The address arrives with the quote token, and anything else is refused.
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
