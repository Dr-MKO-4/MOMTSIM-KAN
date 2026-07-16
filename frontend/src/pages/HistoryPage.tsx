import { useCallback, useEffect, useState } from "react";
import {
  History, Trash2, RefreshCw, Play, Layers, Network, BarChart3,
  ChevronDown, ChevronUp,
} from "lucide-react";
import Layout from "../components/Layout";
import EmptyState from "../components/ui/EmptyState";
import { listRuns, deleteRun } from "../api/client";
import type { RunEntry } from "../types/api";

const TYPE_META: Record<string, { label: string; icon: typeof Play; color: string }> = {
  simulation:  { label: "Simulation",     icon: Play,     color: "text-accent-blue" },
  features:    { label: "Features",        icon: Layers,   color: "text-accent-green" },
  kan:         { label: "Validation KAN",  icon: Network,  color: "text-accent-purple" },
  calibration: { label: "Calibration",     icon: BarChart3, color: "text-accent-amber" },
};

const TYPE_FILTERS = [
  { value: "",            label: "Tous" },
  { value: "simulation",  label: "Simulation" },
  { value: "features",    label: "Features" },
  { value: "kan",         label: "KAN" },
  { value: "calibration", label: "Calibration" },
];

function RunCard({ run, onDelete }: { run: RunEntry; onDelete: (id: string) => void }) {
  const [expanded, setExpanded] = useState(false);
  const meta = TYPE_META[run.run_type] ?? { label: run.run_type, icon: History, color: "text-text-muted" };
  const Icon = meta.icon;
  const s = run.summary;

  const formatTs = (ts: string) => {
    const [date, time] = ts.split("_");
    return `${date} ${time?.replace(/(\d{2})(\d{2})(\d{2})/, "$1:$2:$3") ?? ""}`;
  };

  return (
    <div className="card p-0 overflow-hidden">
      <div
        className="flex items-center gap-4 px-4 py-3 cursor-pointer hover:bg-bg-hover transition-colors duration-150"
        onClick={() => setExpanded((e) => !e)}
        role="button"
        aria-expanded={expanded}
        tabIndex={0}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") setExpanded((v) => !v); }}
      >
        <Icon className={`w-4 h-4 flex-shrink-0 ${meta.color}`} aria-hidden="true" />

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-text-primary">{meta.label}</span>
            <span className="text-2xs text-text-dim font-mono">{formatTs(run.timestamp)}</span>
          </div>
          {s.plain_summary && (
            <p className="text-xs text-text-muted mt-0.5 truncate">{s.plain_summary}</p>
          )}
        </div>

        <div className="flex items-center gap-3 flex-shrink-0">
          {s.fraud_rate !== undefined && (
            <span className="font-mono text-xs text-accent-fraud">
              {(s.fraud_rate * 100).toFixed(1)}% fraude
            </span>
          )}
          {s.decision && (
            <span className={`text-xs font-mono ${
              s.decision === "KAN valide" ? "text-accent-green" :
              s.decision === "Transformations requises" ? "text-accent-amber" : "text-accent-fraud"
            }`}>
              {s.decision}
            </span>
          )}
          <button
            className="p-1.5 rounded-lg text-text-dim hover:text-accent-fraud hover:bg-accent-fraud/10
                       transition-colors duration-150"
            onClick={(e) => { e.stopPropagation(); onDelete(run.id); }}
            aria-label="Supprimer ce run"
            title="Supprimer"
          >
            <Trash2 className="w-3.5 h-3.5" aria-hidden="true" />
          </button>
          {expanded
            ? <ChevronUp   className="w-4 h-4 text-text-dim" aria-hidden="true" />
            : <ChevronDown className="w-4 h-4 text-text-dim" aria-hidden="true" />
          }
        </div>
      </div>

      {expanded && (
        <div className="border-t border-border px-4 py-3 bg-bg-secondary">
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
            {s.n_transactions !== undefined && (
              <div>
                <p className="text-2xs text-text-dim uppercase tracking-widest mb-0.5">Transactions</p>
                <p className="font-mono text-sm text-text-primary">{s.n_transactions.toLocaleString("fr-FR")}</p>
              </div>
            )}
            {s.fraud_rate !== undefined && (
              <div>
                <p className="text-2xs text-text-dim uppercase tracking-widest mb-0.5">Taux fraude</p>
                <p className="font-mono text-sm text-accent-fraud">{(s.fraud_rate * 100).toFixed(2)}%</p>
              </div>
            )}
            {s.n_rows !== undefined && (
              <div>
                <p className="text-2xs text-text-dim uppercase tracking-widest mb-0.5">Lignes features</p>
                <p className="font-mono text-sm text-text-primary">{s.n_rows.toLocaleString("fr-FR")}</p>
              </div>
            )}
            {s.VE2 !== undefined && (
              <div>
                <p className="text-2xs text-text-dim uppercase tracking-widest mb-0.5">VE₂</p>
                <p className={`font-mono text-sm ${s.VE2 >= 0.4 ? "text-accent-green" : "text-accent-fraud"}`}>
                  {s.VE2.toFixed(3)}
                </p>
              </div>
            )}
            {s.J_Fisher !== undefined && (
              <div>
                <p className="text-2xs text-text-dim uppercase tracking-widest mb-0.5">J_Fisher</p>
                <p className={`font-mono text-sm ${s.J_Fisher > 1 ? "text-accent-green" : "text-accent-fraud"}`}>
                  {s.J_Fisher.toFixed(3)}
                </p>
              </div>
            )}
            {s.sse_final !== undefined && (
              <div>
                <p className="text-2xs text-text-dim uppercase tracking-widest mb-0.5">SSE final</p>
                <p className="font-mono text-sm text-text-primary">{s.sse_final.toFixed(1)}</p>
              </div>
            )}
          </div>

          {s.fraud_by_scenario && Object.keys(s.fraud_by_scenario).length > 0 && (
            <div className="mt-3">
              <p className="text-2xs text-text-dim uppercase tracking-widest mb-1.5">Répartition fraude</p>
              <div className="flex flex-wrap gap-2">
                {Object.entries(s.fraud_by_scenario).map(([sc, pct]) => (
                  <span key={sc} className="font-mono text-2xs text-text-muted">
                    {sc}&nbsp;<span className="text-accent-blue">{(pct * 100).toFixed(1)}%</span>
                  </span>
                ))}
              </div>
            </div>
          )}

          <p className="mt-3 text-2xs text-text-dim font-mono truncate">
            Dossier : {run.folder}
          </p>
        </div>
      )}
    </div>
  );
}

export default function HistoryPage() {
  const [runs, setRuns]           = useState<RunEntry[]>([]);
  const [loading, setLoading]     = useState(false);
  const [filterType, setFilterType] = useState("");

  const fetchRuns = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listRuns(filterType || undefined, 50);
      setRuns(data);
    } catch {
      setRuns([]);
    } finally {
      setLoading(false);
    }
  }, [filterType]);

  useEffect(() => { fetchRuns(); }, [fetchRuns]);

  const handleDelete = useCallback(async (id: string) => {
    try {
      await deleteRun(id);
      setRuns((prev) => prev.filter((r) => r.id !== id));
    } catch {
      // silently ignore
    }
  }, []);

  return (
    <Layout
      title="Historique des runs"
      subtitle="Runs persistés — SQLite registry + dossier runs/"
    >
      <div className="space-y-4">
        {/* Toolbar */}
        <div className="flex items-center gap-3 flex-wrap">
          <div className="flex gap-1">
            {TYPE_FILTERS.map((f) => (
              <button
                key={f.value}
                className={[
                  "btn-sm",
                  filterType === f.value
                    ? "bg-accent-blue text-white"
                    : "btn-secondary text-text-muted",
                ].join(" ")}
                onClick={() => setFilterType(f.value)}
              >
                {f.label}
              </button>
            ))}
          </div>

          <button
            className="btn-ghost ml-auto"
            onClick={fetchRuns}
            disabled={loading}
            aria-label="Rafraîchir"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin-slow" : ""}`} aria-hidden="true" />
            Actualiser
          </button>
        </div>

        {/* Run list */}
        {runs.length === 0 && !loading ? (
          <EmptyState
            icon={History}
            title="Aucun run enregistré"
            description="Les runs terminés (simulation, features, KAN, calibration) sont automatiquement sauvegardés ici avec leurs métadonnées."
          />
        ) : (
          <div className="space-y-2">
            {runs.map((run) => (
              <RunCard key={run.id} run={run} onDelete={handleDelete} />
            ))}
          </div>
        )}

        {loading && runs.length === 0 && (
          <div className="flex justify-center py-12">
            <RefreshCw className="w-5 h-5 text-text-dim animate-spin-slow" aria-hidden="true" />
          </div>
        )}
      </div>
    </Layout>
  );
}
