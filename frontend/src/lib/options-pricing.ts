/**
 * Black-76: an option's price on the forward, for valuing a position before
 * expiry (the positions page). Held to ``app.services.options_math.black76``
 * by the golden file (``tests/test_options_strategy_golden.py``), within
 * the normal CDF's own error. At or past expiry, or with no volatility
 * left, it is the discounted intrinsic value.
 */
import { normCdf } from "./options-strategy";

export function black76(forward: number, strike: number, years: number, vol: number, discount: number, call: boolean): number {
  if (years <= 0 || vol <= 0) {
    return discount * (call ? Math.max(forward - strike, 0) : Math.max(strike - forward, 0));
  }
  const spread = vol * Math.sqrt(years);
  const d1 = (Math.log(forward / strike) + (spread * spread) / 2) / spread;
  const d2 = d1 - spread;
  return call
    ? discount * (forward * normCdf(d1) - strike * normCdf(d2))
    : discount * (strike * normCdf(-d2) - forward * normCdf(-d1));
}
