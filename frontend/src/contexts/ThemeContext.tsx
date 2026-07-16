import { createContext, useCallback, useContext, useEffect, useState } from "react";

type Theme = "dark" | "light";

interface ThemeCtx {
  theme: Theme;
  toggle: () => void;
}

// ── Token values per theme ──────────────────────────────────────────────────
const DARK_VARS: Record<string, string> = {
  "--bg-primary-rgb":   "13 15 24",
  "--bg-secondary-rgb": "22 25 41",
  "--bg-card-rgb":      "28 32 53",
  "--bg-hover-rgb":     "32 36 64",
  "--text-primary-rgb": "226 232 240",
  "--text-muted-rgb":   "148 163 184",
  "--text-dim-rgb":     "78 90 114",
  "--border-rgb":       "37 43 63",
  "--border-hover-rgb": "59 130 246",
  "--border-focus-rgb": "59 130 246",
  "--scrollbar-track":  "#161929",
  "--scrollbar-thumb":  "#252B3F",
};

const LIGHT_VARS: Record<string, string> = {
  "--bg-primary-rgb":   "248 250 252",
  "--bg-secondary-rgb": "255 255 255",
  "--bg-card-rgb":      "255 255 255",
  "--bg-hover-rgb":     "241 245 249",
  "--text-primary-rgb": "15 23 42",
  "--text-muted-rgb":   "71 85 105",
  "--text-dim-rgb":     "148 163 184",
  "--border-rgb":       "226 232 240",
  "--border-hover-rgb": "59 130 246",
  "--border-focus-rgb": "59 130 246",
  "--scrollbar-track":  "#F1F5F9",
  "--scrollbar-thumb":  "#CBD5E1",
};

function applyTheme(theme: Theme) {
  const root = document.documentElement;
  const vars = theme === "light" ? LIGHT_VARS : DARK_VARS;

  // Set inline style properties — guaranteed max specificity, works regardless
  // of whether Tailwind CSS was rebuilt with variable-based colors.
  Object.entries(vars).forEach(([prop, value]) => {
    root.style.setProperty(prop, value);
  });

  // Also update background/color on html directly so the flash-of-wrong-color is gone
  root.style.backgroundColor = theme === "light" ? "#F8FAFC" : "#0D0F18";
  root.style.color           = theme === "light" ? "#0F172A" : "#E2E8F0";

  // Keep data-theme for CSS badge overrides in index.css
  if (theme === "light") {
    root.setAttribute("data-theme", "light");
  } else {
    root.removeAttribute("data-theme");
  }
}

// ── Context ─────────────────────────────────────────────────────────────────
const ThemeContext = createContext<ThemeCtx>({ theme: "dark", toggle: () => {} });

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setTheme] = useState<Theme>(() => {
    try {
      return (localStorage.getItem("momtsim-theme") as Theme) ?? "dark";
    } catch {
      return "dark";
    }
  });

  // Apply on mount and whenever theme changes
  useEffect(() => {
    applyTheme(theme);
    try { localStorage.setItem("momtsim-theme", theme); } catch { /* */ }
  }, [theme]);

  const toggle = useCallback(() => {
    setTheme((t) => (t === "dark" ? "light" : "dark"));
  }, []);

  return (
    <ThemeContext.Provider value={{ theme, toggle }}>
      {children}
    </ThemeContext.Provider>
  );
}

export const useTheme = () => useContext(ThemeContext);
