import { createContext, useContext, useEffect } from "react";

interface ThemeCtx {
  theme: "light";
}

/* Les couleurs sont définies par les variables CSS de index.css. On retire ici
   d'éventuels styles en ligne posés par une version précédente de l'application. */
const LEGACY_VARS = [
  "--bg-primary-rgb", "--bg-secondary-rgb", "--bg-card-rgb", "--bg-hover-rgb",
  "--text-primary-rgb", "--text-muted-rgb", "--text-dim-rgb",
  "--border-rgb", "--border-hover-rgb", "--border-focus-rgb",
  "--scrollbar-track", "--scrollbar-thumb",
];

const ThemeContext = createContext<ThemeCtx>({ theme: "light" });

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  useEffect(() => {
    const root = document.documentElement;
    LEGACY_VARS.forEach((v) => root.style.removeProperty(v));
    root.style.removeProperty("background-color");
    root.style.removeProperty("color");
    root.removeAttribute("data-theme");
  }, []);

  return (
    <ThemeContext.Provider value={{ theme: "light" }}>
      {children}
    </ThemeContext.Provider>
  );
}

export const useTheme = () => useContext(ThemeContext);
