import { useEffect, useState } from "react";
import { getHealth } from "../api/client";
import type { HealthStatus } from "../types/api";

interface Props {
  title: string;
  subtitle?: string;
}

function StatusDot({ ok }: { ok: boolean }) {
  return (
    <span
      className={`inline-block w-2 h-2 rounded-full ${ok ? "bg-accent-green" : "bg-text-dim"}`}
    />
  );
}

export default function TopBar({ title, subtitle }: Props) {
  const [health, setHealth] = useState<HealthStatus | null>(null);

  useEffect(() => {
    getHealth()
      .then(setHealth)
      .catch(() => setHealth(null));
  }, []);

  return (
    <header className="flex items-center justify-between px-6 py-3 border-b border-border bg-bg-secondary sticky top-0 z-10">
      <div>
        <h1 className="text-base font-semibold text-text-primary">{title}</h1>
        {subtitle && <p className="text-xs text-text-muted mt-0.5">{subtitle}</p>}
      </div>

      {health && (
        <div className="flex items-center gap-4 text-2xs text-text-dim font-mono">
          <span className="flex items-center gap-1.5">
            <StatusDot ok={health.files.fraudScenariosConfig} />
            config
          </span>
          <span className="flex items-center gap-1.5">
            <StatusDot ok={health.files.rawLog_torch} />
            rawLog
          </span>
          <span className="flex items-center gap-1.5">
            <StatusDot ok={health.files.featuresLog} />
            features
          </span>
          <span className="flex items-center gap-1.5">
            <StatusDot ok={health.files.calibrated_probas} />
            probas
          </span>
        </div>
      )}
    </header>
  );
}
