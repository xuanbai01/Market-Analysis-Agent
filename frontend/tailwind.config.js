/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Phase 4.0 — Strata design tokens. Slate base + 9 semantic
        // accents (one per metric category) + 4 state colors. Mirrors
        // the design system pinned in
        // docs/adr/0005-symbol-centric-dashboard.md.
        strata: {
          // 9-step slate base (dark theme).
          canvas: "#0a0d12", // page background
          surface: "#0e1116", // cards / panels
          raise: "#141923", // raised / hover
          line: "#1f2630", // hairline rules
          border: "#2a3343", // card border
          muted: "#5a6473", // meta / labels
          dim: "#8892a0", // secondary text
          fg: "#e6e9ef", // body text
          hi: "#f5f7fb", // headings

          // 9 category accents — same chroma + lightness, hue rotation.
          // Locked to backend metric categories so colors carry meaning.
          valuation: "#6cb6ff",
          quality: "#7ad0a6",
          growth: "#c2d97a",
          cashflow: "#e8c277",
          balance: "#e89c6f",
          earnings: "#d68dc6",
          peers: "#9b8ddb",
          macro: "#7e9ad4",
          risk: "#e57c6e",

          // 4 state colors.
          pos: "#5fbf8a",
          neg: "#e57c6e",
          neutral: "#8892a0",
          highlight: "#7e9ad4",
        },
        // Confidence-tier palette — kept for the existing
        // ConfidenceBadge until 4.1+ replaces it with state-color usage.
        confidence: {
          high: "#15803d",
          medium: "#b45309",
          low: "#b91c1c",
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
      letterSpacing: {
        // Used for category labels (eyebrows) per the design system.
        kicker: "0.18em",
      },
    },
  },
  plugins: [],
};
