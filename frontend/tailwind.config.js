/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: {
          primary: "#0F1117",
          secondary: "#1A1D27",
          card: "#1E2130",
        },
        accent: {
          blue: "#3B82F6",
          fraud: "#EF4444",
          green: "#22C55E",
          amber: "#F59E0B",
          purple: "#A78BFA",
        },
        text: {
          primary: "#E2E8F0",
          muted: "#94A3B8",
          dim: "#64748B",
        },
        border: {
          DEFAULT: "#2D3348",
          focus: "#3B82F6",
        },
      },
      fontFamily: {
        sans: ["Fira Sans", "Inter", "system-ui", "sans-serif"],
        mono: ["Fira Code", "JetBrains Mono", "monospace"],
      },
      fontSize: {
        "2xs": "0.65rem",
      },
    },
  },
  plugins: [],
};
