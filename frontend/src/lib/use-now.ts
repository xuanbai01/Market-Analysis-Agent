import { useEffect, useState } from "react";

/** The time, a fresh one every ``everyMs`` while ``active``: ages such as
 * "quotes 8s old" keep counting between reads instead of freezing. */
export function useNow(everyMs: number, active = true): Date {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    if (!active) return;
    setNow(new Date());
    const id = setInterval(() => setNow(new Date()), everyMs);
    return () => clearInterval(id);
  }, [everyMs, active]);
  return now;
}
