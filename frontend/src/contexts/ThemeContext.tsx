import { createContext, useContext, useEffect } from "react";

interface ThemeCtx {
  theme: "light";
}

const LIGHT_VARS: Record<string, string> = {
  "--bg-primary-rgb":   "248 250 252",
  "--bg-secondary-rgb": "255 255 255",
  "--bg-card-rgb":      "255 255 255",
  "--bg-hover-rgb":     "241 245 249",
  "--text-primary-rgb": "15 23 42",
  "--text-muted-rgb":   "71 85 105",
  "--text-dim-rgb":     "148 163 184",
  "--border-rgb":       "226 232 240",
  "--border-hover-rgb": "37 99 235",
  "--border-focus-rgb": "37 99 235",
  "--scrollbar-track":  "#F1F5F9",
  "--scrollbar-thumb":  "#CBD5E1",
};

function applyLight() {
  const root = document.documentElement;
  Object.entries(LIGHT_VARS).forEach(([prop, value]) => {
    root.style.setProperty(prop, value);
  });
  root.style.backgroundColor = "#F8FAFC";
  root.style.color = "#0F172A";
  root.removeAttribute("data-theme");
}

const ThemeContext = createContext<ThemeCtx>({ theme: "light" });

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    applyLight();
  }, []);

  return (
    <ThemeContext.Provider value={{ theme: "light" }}>
      {children}
    </ThemeContext.Provider>
  );
}

export const useTheme = () => useContext(ThemeContext);
