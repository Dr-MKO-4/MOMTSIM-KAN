import { useState } from "react";
import Layout from "../components/Layout";
import JobTracker from "../components/JobTracker";
import PlotlyEmbed from "../components/PlotlyEmbed";
import StatCard from "../components/StatCard";
import { startKANValidation } from "../api/client";
import type { KANValidationResult } from "../types/api";

function DecisionBadge({ decision }: { decision: string }) {
  const cfg: Record<string, { cls: string; icon: string }> = {
    "KAN valide": { cls: "badge-green", icon: "✓" },
    "Transformations requises": { cls: "badge-amber", icon: "⚠" },
    "Architecture alternative": { cls: "badge-red", icon: "✗" },
  };
  const { cls, icon } = cfg[decision] ?? { cls: "badge-gray", icon: "?" };
  return (
    <span className={`${cls} text-sm px-3 py-1`}>
      {icon} {decision}
    </span>
  );
}

function MetricRow({ label, value, threshold, unit = "", invert = false }: {
  label: string; value: number; threshold: number; unit?: string; invert?: boolean;
}) {
  const ok = invert ? value < threshold : value >= threshold;
  return (
    <div className="flex items-center justify-between py-2 border-b border-border/50 last:border-0">
      <span className="text-sm font-mono text-text-muted">{label}</span>
      <div className="flex items-center gap-2">
        <span className={`font-mono text-sm font-medium ${ok ? "text-accent-green" : "text-accent-fraud"}`}>
          {typeof value === "number" ? value.toFixed(4) : value}{unit}
        </span>
        <span className="text-2xs text-text-dim">(seuil: {threshold}{unit})</span>
      </div>
    </div>
  );
}

export default function KANPage() {
  const [jobId, setJobId] = useState<string | null>(null);
  const [result, setResult] = useState<KANValidationResult | null>(null);
  const [loading, setLoading] = useState(false);

  const launch = async () => {
    setLoading(true);
    setResult(null);
    try {
      const { job_id } = await startKANValidation();
      setJobId(job_id);
    } finally {
      setLoading(false);
    }
  };

  const onDone = (r: Record<string, unknown>) => {
    setResult(r as unknown as KANValidationResult);
  };

  return (
    <Layout
      title="Validation Topologique KAN"
      subtitle="Quick Decision Rule — section 4.1 du mémoire (éqs. 4.1–4.7)"
    >
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        {/* Panneau gauche */}
        <div className="xl:col-span-1 space-y-4">
          <div className="card">
            <h2 className="section-title">Critères de validation</h2>
            <p className="section-subtitle">Règle de décision — éq. 4.7</p>
            <div className="space-y-3 mt-2 text-xs font-mono">
              <div className="p-3 bg-bg-secondary rounded-lg border border-border">
                <p className="text-accent-green font-medium mb-1">KAN valide</p>
                <p className="text-text-muted">J_Fisher &gt; 1 <span className="text-text-dim">ET</span></p>
                <p className="text-text-muted">VE₂ ≥ 0.40 <span className="text-text-dim">ET</span></p>
                <p className="text-text-muted">D̄_KS &lt; 0.15</p>
              </div>
              <div className="p-3 bg-bg-secondary rounded-lg border border-border">
                <p className="text-accent-amber font-medium mb-1">Transformations requises</p>
                <p className="text-text-muted">J_Fisher &gt; 1 <span className="text-text-dim">ET</span></p>
                <p className="text-text-muted">features non-normales (KS ≥ 0.15)</p>
              </div>
              <div className="p-3 bg-bg-secondary rounded-lg border border-border">
                <p className="text-accent-fraud font-medium mb-1">Architecture alternative</p>
                <p className="text-text-muted">autres cas</p>
              </div>
            </div>
          </div>

          <button
            className="btn-primary w-full text-sm"
            onClick={launch}
            disabled={loading || (jobId !== null && result === null)}
          >
            {loading ? "Lancement…" : "κ Valider la topologie KAN"}
          </button>

          <p className="text-xs text-text-dim text-center">
            Requiert featuresLog.csv (feature engineering préalable)
          </p>

          <JobTracker jobId={jobId} onDone={onDone} onError={() => {}} />
        </div>

        {/* Résultats */}
        <div className="xl:col-span-2 space-y-6">
          {result ? (
            <>
              {/* Décision */}
              <div className="card flex items-center justify-between">
                <div>
                  <p className="text-xs text-text-dim uppercase tracking-widest mb-1">Décision (éq. 4.7)</p>
                  <DecisionBadge decision={result.decision} />
                </div>
                <div className="text-right">
                  <p className="text-xs text-text-dim">k composantes pour VE80</p>
                  <p className="font-mono text-xl text-text-primary font-bold">{result.k_for_VE80}</p>
                </div>
              </div>

              {/* Métriques */}
              <div className="card">
                <h3 className="text-sm font-medium text-text-primary mb-3">Métriques de validation</h3>
                <MetricRow label="VE₂ (éq. 4.2)" value={result.VE2} threshold={0.40} />
                <MetricRow label="J_Fisher (éq. 4.4)" value={result.J_Fisher} threshold={1} />
                <MetricRow label="D̄_KS (éq. 4.5)" value={result.D_KS_mean} threshold={0.15} invert />
              </div>

              {/* Features à transformer */}
              {result.features_needing_transform.length > 0 && (
                <div className="card border-amber-800/50">
                  <h3 className="text-sm font-medium text-accent-amber mb-2">
                    Features nécessitant log(1+x)
                  </h3>
                  <div className="flex flex-wrap gap-2">
                    {result.features_needing_transform.map((f) => (
                      <span key={f} className="badge-amber font-mono">{f}</span>
                    ))}
                  </div>
                </div>
              )}

              {/* Couverture grille */}
              <div className="card">
                <h3 className="text-sm font-medium text-text-primary mb-3">
                  Couverture de grille ρ_coverage (éq. 4.6) — seuil [0.8, 1.0]
                </h3>
                <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                  {Object.entries(result.grid_coverage).map(([feat, rho]) => {
                    const ok = rho >= 0.8 && rho <= 1.0;
                    return (
                      <div key={feat} className="flex items-center justify-between bg-bg-secondary rounded px-2 py-1.5">
                        <span className="text-2xs font-mono text-text-muted truncate">{feat}</span>
                        <span className={`font-mono text-xs ml-2 flex-shrink-0 ${ok ? "text-accent-green" : "text-accent-fraud"}`}>
                          {rho.toFixed(2)}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Graphiques */}
              {result.charts.pca_projection && (
                <PlotlyEmbed html={result.charts.pca_projection} title="Projection PCA — espace latent Z" height={520} />
              )}
              {result.charts.ks_summary && (
                <PlotlyEmbed html={result.charts.ks_summary} title="Test KS par feature (D_KS vs seuil 0.15)" height={420} />
              )}
            </>
          ) : (
            <div className="card flex flex-col items-center justify-center min-h-[300px] text-center">
              <p className="text-4xl mb-4 text-text-dim font-mono">κ</p>
              <p className="text-sm text-text-muted">
                Lancez la validation topologique sur le featuresLog.
              </p>
              <p className="text-xs text-text-dim mt-1">
                Normalisation → PCA → Fisher → KS → couverture grille → décision
              </p>
            </div>
          )}
        </div>
      </div>
    </Layout>
  );
}
