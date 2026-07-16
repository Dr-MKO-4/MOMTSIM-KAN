import { memo, useCallback, useEffect, useState } from "react";
import { Menu, FileCheck, FileX, Sun, Moon } from "lucide-react";
import { getHealth } from "../api/client";
import { useTheme } from "../contexts/ThemeContext";
import type { HealthStatus } from "../types/api";

interface Props {
  title: string;
  subtitle?: string;
  onMenuClick: () => void;
}

const FILE_LABELS: { key: keyof HealthStatus["files"]; label: string }[] = [
  { key: "fraudScenariosConfig", label: "config" },
  { key: "rawLog_torch",         label: "rawLog" },
  { key: "featuresLog",          label: "features" },
  { key: "calibrated_probas",    label: "probas" },
];

function StatusIndicator({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span
      className="flex items-center gap-1.5"
      title={`${label} : ${ok ? "présent" : "manquant"}`}
      aria-label={`Fichier ${label} ${ok ? "présent" : "manquant"}`}
    >
      {ok
        ? <FileCheck className="w-3 h-3 text-accent-green" aria-hidden="true" />
        : <FileX    className="w-3 h-3 text-text-dim"     aria-hidden="true" />
      }
      <span className={`text-2xs font-mono ${ok ? "text-text-muted" : "text-text-dim"}`}>
        {label}
      </span>
    </span>
  );
}

function TopBar({ title, subtitle, onMenuClick }: Props) {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const { theme, toggle } = useTheme();

  const fetchHealth = useCallback(() => {
    getHealth().then(setHealth).catch(() => setHealth(null));
  }, []);

  useEffect(() => {
    fetchHealth();
    const id = setInterval(fetchHealth, 15_000);
    return () => clearInterval(id);
  }, [fetchHealth]);

  return (
    <header className="flex items-center gap-4 px-5 py-3 border-b border-border bg-bg-secondary sticky top-0 z-10">
      <button
        className="lg:hidden p-1.5 rounded-lg text-text-dim hover:text-text-primary hover:bg-bg-hover transition-colors duration-150"
        onClick={onMenuClick}
        aria-label="Ouvrir le menu"
      >
        <Menu className="w-4 h-4" aria-hidden="true" />
      </button>

      <div className="flex-1 min-w-0">
        <h1 className="page-title truncate">{title}</h1>
        {subtitle && (
          <p className="text-xs text-text-dim mt-0.5 truncate font-mono">{subtitle}</p>
        )}
      </div>

      {health && (
        <div
          className="hidden sm:flex items-center gap-3 flex-shrink-0"
          role="status"
          aria-label="État des fichiers système"
        >
          {FILE_LABELS.map(({ key, label }) => (
            <StatusIndicator key={key} ok={health.files[key]} label={label} />
          ))}
        </div>
      )}

      <button
        className="p-1.5 rounded-lg text-text-dim hover:text-text-primary hover:bg-bg-hover
                   transition-colors duration-150 flex-shrink-0"
        onClick={toggle}
        aria-label={theme === "dark" ? "Passer en thème clair" : "Passer en thème sombre"}
        title={theme === "dark" ? "Thème clair" : "Thème sombre"}
      >
        {theme === "dark"
          ? <Sun  className="w-4 h-4" aria-hidden="true" />
          : <Moon className="w-4 h-4" aria-hidden="true" />
        }
      </button>
    </header>
  );
}

export default memo(TopBar);
