import { memo, useCallback, useEffect, useState } from "react";
import { Menu, FileCheck, FileX, Loader2 } from "lucide-react";
import { getHealth, listJobs } from "../api/client";
import type { HealthStatus, Job } from "../types/api";
import ProgressBar from "./ui/ProgressBar";

interface Props {
  title: string;
  subtitle?: string;
  onMenuClick: () => void;
}

const FILE_LABELS: { key: keyof HealthStatus["files"]; label: string }[] = [
  { key: "fraudScenariosConfig", label: "config" },
  { key: "calibrated_probas",    label: "probas" },
  { key: "rawLog_torch",         label: "rawLog" },
  { key: "featuresLog",          label: "features" },
];

const KIND_LABEL: Record<string, string> = {
  simulation: "Simulation", calibration: "Calibration", features: "Features", kan: "Validation KAN",
};

function StatusIndicator({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span
      className={`flex items-center gap-1 rounded-full px-2 py-1 text-2xs font-medium ${
        ok ? "bg-emerald-50 text-emerald-700" : "bg-slate-100 text-text-dim"}`}
      title={`${label} : ${ok ? "présent" : "manquant"}`}
    >
      {ok ? <FileCheck className="w-3 h-3" aria-hidden="true" /> : <FileX className="w-3 h-3" aria-hidden="true" />}
      {label}
    </span>
  );
}

function TopBar({ title, subtitle, onMenuClick }: Props) {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [active, setActive] = useState<Job[]>([]);

  const fetchHealth = useCallback(() => {
    getHealth().then(setHealth).catch(() => setHealth(null));
  }, []);

  useEffect(() => {
    fetchHealth();
    const id = setInterval(fetchHealth, 15_000);
    return () => clearInterval(id);
  }, [fetchHealth]);

  /* Tâches en cours, visibles depuis toutes les pages */
  useEffect(() => {
    const tick = () => listJobs()
      .then((jobs) => setActive(jobs.filter((j) => j.status === "running" || j.status === "pending")))
      .catch(() => {});
    tick();
    const id = setInterval(tick, 2_000);
    return () => clearInterval(id);
  }, []);

  return (
    <header className="sticky top-0 z-10 border-b border-border/70 bg-white/75 backdrop-blur-md">
      <div className="flex items-center gap-4 px-5 lg:px-8 py-3.5">
        <button className="lg:hidden btn-icon" onClick={onMenuClick} aria-label="Ouvrir le menu">
          <Menu className="w-4 h-4" aria-hidden="true" />
        </button>

        <div className="flex-1 min-w-0">
          <h1 className="page-title truncate">{title}</h1>
          {subtitle && <p className="text-xs text-text-dim mt-0.5 truncate">{subtitle}</p>}
        </div>

        {active.length > 0 && (
          <div className="hidden md:flex flex-col gap-1 w-56" role="status" aria-label="Tâches en cours">
            {active.slice(0, 2).map((j) => (
              <div key={j.job_id} className="flex items-center gap-2">
                <Loader2 className="w-3 h-3 text-accent-blue animate-spin-slow flex-shrink-0" aria-hidden="true" />
                <span className="text-2xs text-text-muted w-20 truncate">{KIND_LABEL[j.kind ?? ""] ?? "Tâche"}</span>
                <ProgressBar value={j.progress} size="xs" indeterminate={!!j.indeterminate} className="flex-1" />
                <span className="text-2xs font-mono text-text-dim w-8 text-right">{j.progress}%</span>
              </div>
            ))}
          </div>
        )}

        {health && (
          <div className="hidden xl:flex items-center gap-1.5 flex-shrink-0" role="status" aria-label="État des fichiers">
            {FILE_LABELS.map(({ key, label }) => (
              <StatusIndicator key={key} ok={health.files[key]} label={label} />
            ))}
          </div>
        )}
      </div>
    </header>
  );
}

export default memo(TopBar);
