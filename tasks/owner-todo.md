# Owner to-do: positions page and trade copy

These are the steps only you can do. Claude can't do them, because each one involves a secret or your own account. Work through them in order. Claude ticks each one off here once you say it's done.

## 1. Set the owner key (now, any time)

The owner pages answer 404 until this is set.

- [ ] **Run the steps on your PC.** In PowerShell, from the repo, run the five lines in [docs/deployment.md §10](../docs/deployment.md) step 1. They make a random key, import it into Fly (which restarts the app), and copy the key to your clipboard.
- [ ] **Save the key in your password manager** right away. Make an entry for `https://market-analysis-agent-red.vercel.app` with the username `market-agent-owner` and the clipboard as the password. Then clear the clipboard with `Set-Clipboard -Value ' '`.
- [ ] **Check that the entry synced** to your other PC's password manager.

## 2. Unlock the pages on each PC (after PR 3 is deployed)

- [ ] **First PC:** open `/positions`. Your password manager should offer to fill the owner key; if it doesn't, paste it.
- [ ] **Second PC:** do the same.
- [ ] **Compare the figures** on `/positions` with tastytrade's own app: marks, quantities, Greeks. Claude can't see your values, so this check is yours.

## 3. Set the trade-copy key (after PR 4 is merged)

- [ ] **Run the PowerShell steps** that PR 4 adds to docs/deployment.md, to set `OWNER_VAULT_KEY`.
- [ ] **Save that key in your password manager too.** If it's lost, the stored copy can't be read, but tastytrade still has your full history, so the copy can be rebuilt with a new key.
- [ ] **Open `/trades` once** to fill the copy, then check its count against tastytrade's history.

## 4. Monday 2026-11-16 (market hours)

- [ ] **Your broker cross-checks:** compare the options page's figures with tastytrade for one or two tickers you trade.
- [ ] **Leave the probe to Claude.** During the session it reads real-time quote ages, and whether tastytrade's IVs come as fractions. You don't need to do anything for it.
