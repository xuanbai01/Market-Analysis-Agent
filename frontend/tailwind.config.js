/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Confidence-tier palette. Used by ConfidenceBadge — kept here
        // (not inline) so a future rebranding doesn't have to chase
        // hex values across components.
        confidence: {
          high: "#15803d", // green-700
          medium: "#b45309", // amber-700
          low: "#b91c1c", // red-700
        },
      },
    },
  },
  plugins: [],
};
