/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: {
          primary:   "rgb(var(--bg-primary-rgb)   / <alpha-value>)",
          secondary: "rgb(var(--bg-secondary-rgb) / <alpha-value>)",
          card:      "rgb(var(--bg-card-rgb)       / <alpha-value>)",
          hover:     "rgb(var(--bg-hover-rgb)      / <alpha-value>)",
        },
        accent: {
          blue:   "#3B82F6",
          fraud:  "#EF4444",
          green:  "#22C55E",
          amber:  "#F59E0B",
          purple: "#A78BFA",
        },
        text: {
          primary: "rgb(var(--text-primary-rgb) / <alpha-value>)",
          muted:   "rgb(var(--text-muted-rgb)   / <alpha-value>)",
          dim:     "rgb(var(--text-dim-rgb)      / <alpha-value>)",
        },
        border: {
          DEFAULT: "rgb(var(--border-rgb)       / <alpha-value>)",
          hover:   "rgb(var(--border-hover-rgb) / <alpha-value>)",
          focus:   "rgb(var(--border-focus-rgb) / <alpha-value>)",
        },
        status: {
          success: "#22C55E",
          warning: "#F59E0B",
          danger:  "#EF4444",
          info:    "#3B82F6",
          muted:   "#4E5A72",
        },
      },
      fontFamily: {
        sans: ["Fira Sans", "Inter", "system-ui", "sans-serif"],
        mono: ["Fira Code", "JetBrains Mono", "monospace"],
      },
      fontSize: {
        "2xs": ["0.65rem", { lineHeight: "1rem" }],
      },
      borderRadius: {
        card: "0.75rem",
      },
      boxShadow: {
        card: "0 1px 3px 0 rgb(0 0 0 / 0.4), 0 1px 2px -1px rgb(0 0 0 / 0.4)",
        "card-hover": "0 4px 12px 0 rgb(0 0 0 / 0.5)",
        "focus-ring": "0 0 0 2px #3B82F6",
      },
      keyframes: {
        "fade-in": {
          from: { opacity: "0", transform: "translateY(4px)" },
          to:   { opacity: "1", transform: "translateY(0)" },
        },
        "slide-in": {
          from: { opacity: "0", transform: "translateX(-8px)" },
          to:   { opacity: "1", transform: "translateX(0)" },
        },
        "progress-pulse": {
          "0%, 100%": { opacity: "1" },
          "50%":      { opacity: "0.6" },
        },
        "spin-slow": {
          from: { transform: "rotate(0deg)" },
          to:   { transform: "rotate(360deg)" },
        },
      },
      animation: {
        "fade-in":        "fade-in 0.2s ease-out",
        "slide-in":       "slide-in 0.2s ease-out",
        "progress-pulse": "progress-pulse 1.5s ease-in-out infinite",
        "spin-slow":      "spin-slow 1s linear infinite",
      },
    },
  },
  plugins: [],
};
