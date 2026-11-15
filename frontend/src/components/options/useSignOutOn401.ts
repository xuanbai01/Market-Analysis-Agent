/**
 * A 401 from any options request means the stored sign-in is stale: clear
 * it and go to sign-in, as the dashboard does. Returns whether this error
 * is one, so the caller can skip its error banner.
 */
import { useEffect } from "react";
import { useNavigate } from "react-router-dom";

import { ApiError } from "../../lib/api";
import { clearStoredToken } from "../../lib/auth";
import { ROUTES } from "../../lib/routes";

export function useSignOutOn401(error: unknown): boolean {
  const navigate = useNavigate();
  const unauthorized = error instanceof ApiError && error.status === 401;
  useEffect(() => {
    if (unauthorized) {
      clearStoredToken();
      navigate(ROUTES.login, { replace: true });
    }
  }, [unauthorized, navigate]);
  return unauthorized;
}
