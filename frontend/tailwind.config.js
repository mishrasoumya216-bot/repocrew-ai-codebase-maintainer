/** RepoCrew Tailwind theme — dark developer-tool palette. */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#050B14",
        surface: "#0B1624",
        raised: "#101F33",
        line: "#1C3048",
        ink: "#E6F0FA",
        muted: "#8AA0B8",
        accent: "#22D3EE",
        violet: "#8B5CF6",
        success: "#34D399",
        warning: "#FBBF24",
        danger: "#F87171",
        agentTriage: "#FBBF24",
        agentCoder: "#22D3EE",
        agentTester: "#34D399",
        agentReviewer: "#A78BFA",
        agentOrchestrator: "#94A3B8",
        agentGate: "#F472B6",
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
      borderRadius: { card: "12px" },
    },
  },
  plugins: [],
};
