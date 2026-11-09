/**
 * Line icons for the app chrome — 16×16, 1.5 px stroke in currentColor,
 * so each takes its color from the surrounding text. Decorative: the
 * control that holds one carries the accessible name.
 */
import type { ReactNode } from "react";

function Icon({ children }: { children: ReactNode }) {
  return (
    <svg
      viewBox="0 0 16 16"
      width={16}
      height={16}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      className="flex-shrink-0"
    >
      {children}
    </svg>
  );
}

export function IconSearch() {
  return (
    <Icon>
      <circle cx="7" cy="7" r="4.25" />
      <path d="M10.25 10.25 13.5 13.5" />
    </Icon>
  );
}

export function IconHome() {
  return (
    <Icon>
      <path d="M2.75 7.25 8 2.75l5.25 4.5" />
      <path d="M4 6.25v7h3v-3.5h2v3.5h3v-7" />
    </Icon>
  );
}

export function IconCompare() {
  return (
    <Icon>
      <rect x="2.25" y="3" width="4.5" height="10" rx="1" />
      <rect x="9.25" y="3" width="4.5" height="10" rx="1" />
    </Icon>
  );
}

/** A distribution: dots over an axis (cross-company lenses). */
export function IconLens() {
  return (
    <Icon>
      <path d="M2.5 13.5h11" />
      <circle cx="4.5" cy="9.5" r="1" />
      <circle cx="7" cy="6" r="1" />
      <circle cx="9.5" cy="8.5" r="1" />
      <circle cx="12" cy="4" r="1" />
    </Icon>
  );
}

export function IconStar() {
  return (
    <Icon>
      <path d="M8 2.25l1.7 3.6 3.95.45-2.92 2.7.8 3.9L8 10.95 4.47 12.9l.8-3.9-2.92-2.7 3.95-.45z" />
    </Icon>
  );
}

export function IconClock() {
  return (
    <Icon>
      <circle cx="8" cy="8" r="5.75" />
      <path d="M8 5v3.25l2.25 1.5" />
    </Icon>
  );
}

export function IconSignOut() {
  return (
    <Icon>
      <path d="M6.5 2.75H3.75a1 1 0 0 0-1 1v8.5a1 1 0 0 0 1 1H6.5" />
      <path d="M10.25 5 13.25 8l-3 3" />
      <path d="M13 8H6.5" />
    </Icon>
  );
}

export function IconCollapse() {
  return (
    <Icon>
      <path d="M9.5 4.5 6 8l3.5 3.5" />
      <path d="M13 4.5 9.5 8l3.5 3.5" opacity="0.5" />
    </Icon>
  );
}

export function IconExpand() {
  return (
    <Icon>
      <path d="M6.5 4.5 10 8l-3.5 3.5" />
      <path d="M3 4.5 6.5 8 3 11.5" opacity="0.5" />
    </Icon>
  );
}

export function IconClose() {
  return (
    <Icon>
      <path d="M4.5 4.5l7 7M11.5 4.5l-7 7" />
    </Icon>
  );
}

/** The brand mark: three stacked strata, rising left to right. */
export function BrandMark() {
  return (
    <svg
      viewBox="0 0 16 16"
      width={16}
      height={16}
      fill="currentColor"
      aria-hidden="true"
      focusable="false"
    >
      <rect x="2" y="10" width="12" height="2.5" rx="1" />
      <rect x="5" y="6.5" width="9" height="2.5" rx="1" opacity="0.75" />
      <rect x="8" y="3" width="6" height="2.5" rx="1" opacity="0.5" />
    </svg>
  );
}
