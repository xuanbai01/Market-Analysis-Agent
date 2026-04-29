// ESLint flat-config-lite via the legacy .eslintrc.cjs format. Vite ships
// fine with either; we picked .cjs because it's the most copy-pastable
// reference shape across React/TS/Vite tutorials and works without
// surprising people who haven't migrated to flat-config yet.
module.exports = {
  root: true,
  env: { browser: true, es2022: true },
  extends: [
    "eslint:recommended",
    "plugin:@typescript-eslint/recommended",
    "plugin:react/recommended",
    "plugin:react/jsx-runtime",
    "plugin:react-hooks/recommended",
  ],
  ignorePatterns: ["dist", ".eslintrc.cjs", "vite.config.ts"],
  parser: "@typescript-eslint/parser",
  parserOptions: { ecmaVersion: "latest", sourceType: "module" },
  plugins: ["react", "react-hooks"],
  settings: { react: { version: "18.3" } },
  rules: {
    "react/prop-types": "off", // we use TypeScript types instead
    "@typescript-eslint/no-unused-vars": [
      "error",
      { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
    ],
  },
};
