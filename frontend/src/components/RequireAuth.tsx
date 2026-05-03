/**
 * RequireAuth — route guard for authenticated pages.
 *
 * If no token is in localStorage, redirect to /login. Children render
 * unchanged when authed. The original URL is preserved in router
 * state so post-login navigation can route back to where the user
 * was trying to go.
 */
import { Navigate, useLocation } from "react-router-dom";
import type { ReactNode } from "react";

import { getStoredToken } from "../lib/auth";
import { ROUTES } from "../lib/routes";

interface Props {
  children: ReactNode;
}

export function RequireAuth({ children }: Props) {
  const location = useLocation();
  const token = getStoredToken();

  if (!token) {
    return (
      <Navigate
        to={ROUTES.login}
        replace
        state={{ from: location }}
      />
    );
  }

  return <>{children}</>;
}
