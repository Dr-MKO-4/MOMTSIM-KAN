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
          sunken:    "rgb(var(--bg-sunken-rgb)     / <alpha-value>)",
        },
        accent: {
          blue:   "#4F46E5",
          sky:    "#0EA5E9",
          fraud:  "#E11D48",
          green:  "#059669",
          amber:  "#D97706",
          purple: "#7C3AED",
        },
        text: {
          primary: "rgb(var(--text-primary-rgb) / <alpha-value>)",
          muted:   "rgb(var(--text-muted-rgb)   / <alpha-value>)",
          dim:     "rgb(var(--text-dim-rgb)      / <alpha-value>)",
        },
        border: {
          DEFAULT: "rgb(var(--border-rgb)       / <alpha-value>)",
          subtle:  "rgb(var(--border-subtle-rgb) / <alpha-value>)",
          hover:   "rgb(var(--border-hover-rgb) / <alpha-value>)",
          focus:   "rgb(var(--border-focus-rgb) / <alpha-value>)",
        },
        status: {
          success: "#059669",
          warning: "#D97706",
          danger:  "#E11D48",
          info:    "#4F46E5",
          muted:   "#94A3B8",
        },
      },
      fontFamily: {
        sans: ["Inter", "Fira Sans", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "Fira Code", "monospace"],
      },
      fontSize: {
        "2xs": ["0.68rem", { lineHeight: "1rem" }],
      },
      borderRadius: {
        card: "1rem",
      },
      boxShadow: {
        card:         "0 1px 2px 0 rgb(15 23 42 / 0.04), 0 1px 3px 0 rgb(15 23 42 / 0.06)",
        "card-hover": "0 10px 30px -12px rgb(79 70 229 / 0.25), 0 4px 10px -4px rgb(15 23 42 / 0.08)",
        soft:         "0 8px 24px -12px rgb(15 23 42 / 0.18)",
        glow:         "0 0 0 4px rgb(79 70 229 / 0.12)",
        "focus-ring": "0 0 0 3px rgb(79 70 229 / 0.25)",
      },
      backgroundImage: {
        "brand-gradient": "linear-gradient(135deg, #4F46E5 0%, #7C3AED 55%, #0EA5E9 100%)",
        "stripes":        "repeating-linear-gradient(45deg, rgb(255 255 255 / 0.22) 0 10px, transparent 10px 20px)",
      },
      keyframes: {
        "fade-in": {
          from: { opacity: "0", transform: "translateY(6px)" },
          to:   { opacity: "1", transform: "translateY(0)" },
        },
        "slide-in": {
          from: { opacity: "0", transform: "translateX(-8px)" },
          to:   { opacity: "1", transform: "translateX(0)" },
        },
        "progress-pulse": {
          "0%, 100%": { opacity: "1" },
          "50%":      { opacity: "0.55" },
        },
        "spin-slow": {
          from: { transform: "rotate(0deg)" },
          to:   { transform: "rotate(360deg)" },
        },
        "stripes-move": {
          from: { backgroundPosition: "0 0" },
          // période horizontale des rayures à 45° de 20 px : 20·√2 ≈ 28,28 px
          to:   { backgroundPosition: "28.28px 0" },
        },
        shimmer: {
          "0%":   { transform: "translateX(-100%)" },
          "100%": { transform: "translateX(250%)" },
        },
        indeterminate: {
          "0%":   { left: "-35%", width: "35%" },
          "60%":  { left: "100%", width: "45%" },
          "100%": { left: "100%", width: "45%" },
        },
        "ping-soft": {
          "0%":   { transform: "scale(1)", opacity: "0.6" },
          "100%": { transform: "scale(2.2)", opacity: "0" },
        },
      },
      animation: {
        "fade-in":        "fade-in 0.25s ease-out",
        "slide-in":       "slide-in 0.2s ease-out",
        "progress-pulse": "progress-pulse 1.5s ease-in-out infinite",
        "spin-slow":      "spin-slow 1s linear infinite",
        "stripes":        "stripes-move 0.9s linear infinite",
        shimmer:          "shimmer 1.8s ease-in-out infinite",
        indeterminate:    "indeterminate 1.6s cubic-bezier(0.65, 0, 0.35, 1) infinite",
        "ping-soft":      "ping-soft 1.6s cubic-bezier(0, 0, 0.2, 1) infinite",
      },
    },
  },
  plugins: [],
};
