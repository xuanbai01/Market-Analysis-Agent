---
name: pre-pr-check
description: Checks this branch's diff against main for the defect kinds DeepSeek's CI review kept finding on #128–#131 (provider fields, failure paths, status codes, time, displayed numbers, missing vs zero, tests that can't fail, event-loop work, shared caches, what the page names, docs drift). Run before opening a PR.
---

Check the diff against `main` for the defects the AI review in CI found again and again on #128–#131: about 100 fixes over 8–12 rounds a PR, and about 40 findings answered "Not changed". Each one caught here saves a review round. The stories are in `docs/changelog.md`, under "From #128's AI review" through "From #131's eighth AI review".

## Steps

1. Run `git diff main...HEAD --stat`, then read `git diff main...HEAD` in full. If it's empty, say so and stop.
2. For each category below that the diff touches, run its check and read the code around the hunk: what a new line calls and what calls it. Most of these defects sit just outside the hunk.
3. Fix what you find test-first, as usual, before opening the PR.
4. Report one line per category: clean, fixed (what), or not touched. Anything you chose to leave gets a reason, ready for the changelog's "Not changed".

## Categories (most frequent first)

### 1. A provider field of another type, or missing
Look for a field from tastytrade's or Yahoo's answer that's assumed to have one type.
- #129: a page count sent as 2.0, or not at all, stopped the read after the first page; an estimated-fee flag sent as `"true"` was missed; an id sent as digits dropped its row.
- #131: an expiry or assignment sent without a buy or sell. #128: a mark of 0 (a halted stock) was taken as a price.
**Check:** for every new `.get(` or `["…"]` on a provider dict, ask what `"12"`, `12.0`, `"true"`, `0`, `""`, `None` and a list do. Use the readers that exist (`owner_positions.finite_number`, `_count`, `items_of(strict=True)`, `owner_trades._whole`, `_estimated`), and write one parametrized test over those values.

### 2. A failure that becomes a 500, or a false "done"
Look for a deadline, a dropped DB connection, a cancelled request or a wrong-shaped answer with no path to a response that says why.
- #129: a sync past its 120 s deadline was a 500, and so was Neon dropping the connection mid-write. A visit in the minute after a failed sync was told the copy was updated, and a visit closed mid-write was reported as done.
- #130: Yahoo's delayed price stood in under the "Live" label when tastytrade sent none. A symbol with no options read as an outage: empty isn't failed.
**Check:** for each new `await` on a provider or the DB, list what it can raise (`TimeoutError`, `CancelledError`, `sqlalchemy.exc.DBAPIError`, `TastytradeUnavailable`, a `KeyError` or `TypeError` from the answer's shape). Write a test that raises each and asserts the status and the reason, then read what the next visit is told.

### 3. A status code the frontend reads as something else
- #130: an unlisted expiry answered 404, which the page reads as "no owner key", so it would have signed the owner out of every owner page (now a 422). On the Live switch only a 403 clears the key, since a 404 there may be a deploy in progress.
- #129, #130: a 401 on the CSV download and on the live read didn't sign out like the other fetchers.
**Check:** compare each new route's statuses with `isOwnerKeyRefused` and the 401 handling in `lib/owner-api.ts` and `lib/api.ts`. A new fetcher handles 401, 403, 404, 422, 429 and 503 the way its neighbours do, and stops polling on an answer that won't change (#130's 422).

### 4. Time
Look for a fixed hour, a UTC date, or the clock where the quote time belongs.
- #128: every expiry closed at 21:00 UTC: an hour late in summer, three on a half day. The sessions left didn't count today's before the open.
- #131: a fill at 8 pm New York on Oct 31 was booked to November (UTC). #130: an expiry that had closed was priced at a negative time to expiry.
**Check:** `git diff main...HEAD | grep -nE '^\+.*(21:00|20:00|16:00|[Uu][Tt][Cc]|\.date\(\)|toISOString|getUTC|new Date\()'`. Go through `market_calendar` (`session_close`, `quote_time`, `market_open`, `sessions_between`, `et_date`). Test at 9 am New York (before the open), at 1:30 pm on 27 Nov 2026 (a half day), in July and in December (EDT, EST), at 8 pm New York on a month's last day, and after an expiry's close. Ages on screen keep ticking between reads (`lib/use-now.ts`, #130).

### 5. Numbers shown to a reader
Look for rounding at the wrong step, a sign, float noise.
- #128: "moves like −0 shares": the sign was taken before rounding.
- #129: fees written as 1.1400000000000001; a fee credited back added to the fees; a fractional share shown rounded.
**Check:** grep the diff for `toFixed`, `Math.round`, `round(`, `:.2f`, `Intl.NumberFormat`. Test −0.4, a sum of fees like 0.1 + 0.2, 999,600 (a unit rollover: "1.00M", not "1000K", #124), a negative fee and 0.5 shares.

### 6. Missing is not zero, and totals add what the rows show
- #130: a strike with no quote was drawn at $0.00. #128: a leg that couldn't be valued gave a 0% chance of profit, and one holding without a live figure blanked every total.
- #131: a closed position without a computed P&L counted as closed at $0; the fees beside the realized P&L included open positions' fees.
**Check:** grep for `?? 0`, `|| 0`, `or 0`, `.get(…, 0)` and `sum(` over values that can be None. Each total is built from the rows the page lists, and names what it leaves out.

### 7. A test that passes for the wrong reason
- #129: the chunked-insert test wrote 6,000 rows, which fit in one statement; the concurrency test didn't interleave, so it passed without the lock; test databases built from the models lacked the migration's CHECK.
- #128: the page's test didn't pin the clock, and its fixtures' expiries pass in December; the golden check's absolute tolerance was larger than a far out-of-the-money price.
**Check:** for each new test, undo the fix (drop the lock, the chunking, the guard) and watch it fail. Sizes go above the limit, the clock is pinned (`vi.setSystemTime`, a fixed `now`), tolerances are relative to the value, and a warm cache holds a real build (#130).

### 8. CPU work on the event loop, or a connection held across it
- #129: sealing a whole history ran on the loop, and decrypting held the session's connection.
- #130: the nested chain (SPX's is 2.2 MB of JSON) was parsed on the loop; answers over 256 KB now parse off it.
**Check:** in each new `async def`, find loops over provider rows, `json.loads`, crypto and parsing, and run them on the module's executor or `asyncio.to_thread`. No `vault.unseal` and no provider `await` inside `async with session`. A CPU-second costs sixteen on Fly (CLAUDE.md); measure the memory of anything kept (#130's chains: 5.7 MB each).

### 9. Caches, locks and query keys shared between pages
- #128: the positions page read option reports under the options page's query keys, so a visit there got the untracked copy from the browser and recorded no view. A view that waited on the lock, or got the stale copy, recorded none either. A big portfolio's cold reads would have spent the IP's 60 options lookups in one load.
- #130: asyncio marks a lock free before its waiter takes it, so a per-key lock dropped then let a third build run. An expiry missing from the kept chain was read again on every 15 s poll.
**Check:** for each new query key, `grep -rn 'queryKey: \["<name>"' frontend/src` and compare `track`, `staleTime` and `gcTime`. For each server cache, list the paths that skip a side effect (a hit, a waiter, a stale serve) and test each. Count the provider calls and rate-limit lookups one page load makes.

### 10. The page names what's missing and what a figure covers
- #128: a holding with no option data dropped its chance of profit without a word; "five years" was said of a stock listed for three; a bare "Dec 11: " showed with no max pain.
- #131: the realized figure didn't say it held partly closed positions, and the status filter's label didn't say it shows them. #130: open interest from 80 live strikes stood in for the chain's, and "reading" showed as "failed".
**Check:** for each conditional render, filter and total, read its text in every state (loading, failed, empty, partial, filtered), and test each state's text.

### 11. Identity and matching
- #131: positions were keyed by order alone (two accounts can share an order number), and shares delivered beside shares held were read as a close, booking a phantom loss (the one high).
**Check:** every new dict or Map key includes the account. A rule written for one action (an expiry, an assignment) is tested against its neighbours (a delivery, a split).

### 12. Docs and counts
- #129: CLAUDE.md said "never store it" with no word of the trade copy. #116: deployment §9 said a trade-capable grant was refused when it signs in read-only.
**Check:** for each constant or behaviour the diff changes, `grep -rn "<old value or name>" docs CLAUDE.md frontend/README.md`. Update the counts in `docs/testing.md` (`uv run pytest --collect-only -q | tail -1`; `npm test` in `frontend/`), the chunk sizes in `frontend/README.md` if the frontend changed, and the changelog entry.

### 13. Owner data and secrets
From the security reviews beside them: a bad key's start-up error would have quoted a slice of the refresh token; a failed sync's log line could carry an account path; a forced sign-out cleared the shared secret but not the owner key.
**Check:** run `/security-review` for a new route, service or external call, and grep the diff's log calls for `str(exc)`, `{exc}` and provider values.

## Answering "Not changed" findings

Almost every finding left unchanged was wrong because the reviewer saw only the diff. Answer each with a `path:line` and the test that covers it, and list it under the changelog's "Not changed".
- **The guard is in a helper:** "this path isn't on the allowlist" came most often (#129, #130: `tastytrade_client`'s allowlist, an encoded slash, `symbol_path`'s `BF.B` → `BF/B`). "This exception isn't caught": `items_of` raises `TastytradeUnavailable`, the client turns its own timeouts into it, and `parse_occ` raises only `ValueError`. "This value is wrong here": `quote_time` is now during a session, and `cached_underlying` returns nothing without a fetched chain.
- **It's done elsewhere:** the strategy builder already prices from the live chain (twice); the chain route reads any listed expiry; `value` is on every trade; the 503's title carries the route's detail; the CSV fetch throws on a non-2xx before reading the body.
- **The type is known from the source:** the dividend yield is always a float, the shared secret is a plain string, and `probAbove` takes a strike.
- **A trade-off already made:** a GCM failure is loud on purpose; the caps are far beyond this account; a full read after a restart is cheaper; the live route has no per-IP limit behind the owner key; a view recorded twice is an upsert. Point at the ADR or the doc line.
- **A state the provider never sends:** an expiry without an action with a long and a short lot of one contract open (tastytrade nets it away).
- **A diff it didn't fully see:** "`uv.lock` is missing" when it was in the diff.

If the same wrong claim comes back on a second push, a one-line comment at the call site naming the helper stops the third.

## Constraints

- Checks and fixes only this branch's diff; anything unrelated is a follow-up.
- No substitute for the tests, `/security-review` or the live golden eval; run it before them.
