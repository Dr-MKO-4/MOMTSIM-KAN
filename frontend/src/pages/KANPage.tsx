import { useCallback, useState } from "react";
import { Network, CheckCircle2, AlertTriangle, XCircle, Activity, Hash } from "lucide-react";
import Layout from "../components/Layout";
import JobTracker from "../components/JobTracker";
import PlotlyEmbed from "../components/PlotlyEmbed";
import StatCard from "../components/StatCard";
import EmptyState from "../components/ui/EmptyState";
import { startKANValidation } from "../api/client";
import type { KANValidationResult } from "../types/api";

/* ── Decision badge ─────────────────────────────────────────────────────── */
const DECISION_CONFIG: Record<
  string,
  { cls: string; icon: typeof CheckCircle2; iconClass: string }
> = {
  "KAN valide":               { cls: "badge-green",  icon: CheckCircle2,  iconClass: "text-accent-green" },
  "Transformations requises": { cls: "badge-amber",  icon: AlertTriangle, iconClass: "text-accent-amber" },
  "Architecture alternative": { cls: "badge-red",    icon: XCircle,       iconClass: "text-accent-fraud" },
};

function DecisionBadge({ decision }: { decision: string }) {
  const cfg = DECISION_CONFIG[decision] ?? { cls: "badge-gray", icon: Hash, iconClass: "text-text-muted" };
  const Icon = cfg.icon;
  return (
    <span className={`${cfg.cls} text-xs px-3 py-1.5 flex items-center gap-1.5`}>
      <Icon className={`w-3.5 h-3.5 ${cfg.iconClass}`} aria-hidden="true" />
      {decision}
    </span>
  );
}

/* ── Metric row ─────────────────────────────────────────────────────────── */
function MetricRow({
  label, value, threshold, unit = "", invert = false, equation,
}: {
  label: string; value: number; threshold: number;
  unit?: string; invert?: boolean; equation?: string;
}) {
  const ok = invert ? value < threshold : value >= threshold;
  const formatted = typeof value === "number" ? value.toFixed(4) : String(value);
  return (
    <div className="flex items-center justify-between py-2.5 border-b border-border/40 last:border-0">
      <div>
        <span className="text-xs font-mono text-text-muted">{label}</span>
        {equation && <span className="text-2xs text-text-dim ml-2 font-mono">{equation}</span>}
      </div>
      <div className="flex items-center gap-2.5">
        <span className={`font-mono text-sm font-medium ${ok ? "text-accent-green" : "text-accent-fraud"}`}>
          {formatted}{unit}
        </span>
        <span className="text-2xs text-text-dim font-mono">seuil&nbsp;{invert ? "<" : "≥"}&nbsp;{threshold}{unit}</span>
      </div>
    </div>
  );
}

/* ── Page ───────────────────────────────────────────────────────────────── */
export default function KANPage() {
  const [jobId, setJobId]     = useState<string | null>(null);
  const [result, setResult]   = useState<KANValidationResult | null>(null);
  const [loading, setLoading] = useState(false);

  const launch = useCallback(async () => {
    setLoading(true);
    setResult(null);
    try {
      const { job_id } = await startKANValidation();
      setJobId(job_id);
    } finally {
      setLoading(false);
    }
  }, []);

  const onDone = useCallback((r: Record<string, unknown>) => {
    setResult(r as unknown as KANValidationResult);
  }, []);

  const canLaunch = !loading && !(jobId !== null && result === null);

  return (
    <Layout
      title="Validation Topologique KAN"
      subtitle="Quick Decision Rule — section 4.1 du mémoire (éqs. 4.1–4.7)"
    >
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
        {/* ── Left panel ────────────────────────────────────────────── */}
        <div className="xl:col-span-1 space-y-4">
          {/* Decision criteria */}
          <div className="card">
            <h2 className="section-title mb-0.5">Critères de validation</h2>
            <p className="text-xs text-text-muted mb-3">Règle de décision — éq. 4.7</p>
            <div className="space-y-2">
              {[
                {
                  label: "KAN valide",
                  cls: "border-accent-green/30 bg-accent-green/5",
                  titleCls: "text-accent-green",
                  icon: CheckCircle2,
                  conditions: ["J_Fisher > 1", "VE₂ ≥ 0.40", "D̄_KS < 0.15"],
                },
                {
                  label: "Transformations requises",
                  cls: "border-accent-amber/30 bg-accent-amber/5",
                  titleCls: "text-accent-amber",
                  icon: AlertTriangle,
                  conditions: ["J_Fisher > 1", "features non-normales (KS ≥ 0.15)"],
                },
                {
                  label: "Architecture alternative",
                  cls: "border-accent-fraud/30 bg-accent-fraud/5",
                  titleCls: "text-accent-fraud",
                  icon: XCircle,
                  conditions: ["autres cas"],
                },
              ].map((branch) => (
                <div
                  key={branch.label}
                  className={`p-3 rounded-lg border text-xs font-mono ${branch.cls}`}
                >
                  <div className="flex items-center gap-1.5 mb-1.5">
                    <branch.icon className={`w-3.5 h-3.5 ${branch.titleCls}`} aria-hidden="true" />
                    <p className={`font-semibold font-sans text-xs ${branch.titleCls}`}>{branch.label}</p>
                  </div>
                  {branch.conditions.map((c, i) => (
                    <p key={i} className="text-text-muted leading-relaxed">{c}</p>
                  ))}
                </div>
              ))}
            </div>
          </div>

          <button
            className="btn-primary w-full"
            onClick={launch}
            disabled={!canLaunch}
            aria-busy={loading}
          >
            {loading ? (
              <>
                <Activity className="w-4 h-4 animate-spin-slow" aria-hidden="true" />
                Lancement…
              </>
            ) : (
              <>
                <Network className="w-4 h-4" aria-hidden="true" />
                Valider la topologie KAN
              </>
            )}
          </button>

          <p className="caption text-center">
            Requiert featuresLog.csv (feature engineering préalable)
          </p>

          <JobTracker jobId={jobId} onDone={onDone} onError={() => {}} />
        </div>

        {/* ── Results panel ─────────────────────────────────────────── */}
        <div className="xl:col-span-2 space-y-5">
          {result ? (
            <div className="space-y-5 animate-fade-in">
              {/* Decision banner */}
              <div className="card flex flex-wrap items-center justify-between gap-4">
                <div>
                  <p className="text-2xs text-text-dim uppercase tracking-widest mb-1.5 font-mono">
                    Décision — éq. 4.7
                  </p>
                  <DecisionBadge decision={result.decision} />
                </div>
                <div className="text-right">
                  <p className="text-2xs text-text-dim uppercase tracking-widest mb-1">
                    k composantes pour VE80
                  </p>
                  <p className="font-mono text-2xl text-text-primary font-bold leading-none">
                    {result.k_for_VE80}
                  </p>
                </div>
              </div>

              {/* KPI */}
              <div className="grid grid-cols-3 gap-3">
                <StatCard
                  label="VE₂ (éq. 4.2)"
                  value={result.VE2.toFixed(3)}
                  color={result.VE2 >= 0.4 ? "green" : "red"}
                  description="≥ 0.40 requis"
                />
                <StatCard
                  label="J_Fisher (éq. 4.4)"
                  value={result.J_Fisher.toFixed(3)}
                  color={result.J_Fisher > 1 ? "green" : "red"}
                  description="> 1 requis"
                />
                <StatCard
                  label="D̄_KS (éq. 4.5)"
                  value={result.D_KS_mean.toFixed(3)}
                  color={result.D_KS_mean < 0.15 ? "green" : "amber"}
                  description="< 0.15 requis"
                />
              </div>

              {/* Detailed metrics */}
              <div className="card">
                <h3 className="card-title mb-1">Métriques détaillées</h3>
                <p className="text-xs text-text-muted mb-3">Seuils de la règle éq. 4.7</p>
                <MetricRow label="VE₂"      value={result.VE2}       threshold={0.40} equation="éq. 4.2" />
                <MetricRow label="J_Fisher" value={result.J_Fisher}  threshold={1}    equation="éq. 4.4" />
                <MetricRow label="D̄_KS"     value={result.D_KS_mean} threshold={0.15} equation="éq. 4.5" invert />
              </div>

              {/* Features needing transform */}
              {result.features_needing_transform.length > 0 && (
                <div className="card border-amber-800/40">
                  <div className="flex items-center gap-2 mb-2">
                    <AlertTriangle className="w-4 h-4 text-accent-amber flex-shrink-0" aria-hidden="true" />
                    <h3 className="card-title text-accent-amber">
                      Features nécessitant log(1+x)
                    </h3>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {result.features_needing_transform.map((f) => (
                      <span key={f} className="badge-amber font-mono">{f}</span>
                    ))}
                  </div>
                </div>
              )}

              {/* Grid coverage */}
              {Object.keys(result.grid_coverage).length > 0 && (
                <div className="card">
                  <h3 className="card-title mb-0.5">
                    Couverture de grille ρ_coverage — éq. 4.6
                  </h3>
                  <p className="text-xs text-text-muted mb-3">
                    Grille B-spline [-3, 3] — seuil optimal [0.8, 1.0]
                  </p>
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-1.5">
                    {Object.entries(result.grid_coverage).map(([feat, rho]) => {
                      const ok = rho >= 0.8 && rho <= 1.0;
                      return (
                        <div
                          key={feat}
                          className="flex items-center justify-between bg-bg-secondary rounded-lg px-3 py-2"
                          aria-label={`${feat} : ${rho.toFixed(2)} ${ok ? "dans la plage optimale" : "hors plage"}`}
                        >
                          <span className="text-2xs font-mono text-text-muted truncate">{feat}</span>
                          <span className={`font-mono text-xs ml-2 flex-shrink-0 font-medium ${
                            ok ? "text-accent-green" : "text-accent-fraud"
                          }`}>
                            {rho.toFixed(2)}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Charts */}
              {result.charts.pca_projection && (
                <PlotlyEmbed
                  html={result.charts.pca_projection}
                  title="Projection PCA — espace latent Z (éqs. 4.2–4.3)"
                  height={500}
                />
              )}
              {result.charts.ks_summary && (
                <PlotlyEmbed
                  html={result.charts.ks_summary}
                  title="Test KS par feature — D_KS vs seuil 0.15 (éq. 4.5)"
                  height={400}
                />
              )}
            </div>
          ) : (
            <EmptyState
              icon={Network}
              title="Aucun résultat disponible"
              description="Lancez la validation topologique sur featuresLog.csv. Pipeline : normalisation → PCA → Fisher → KS → couverture → décision."
            />
          )}
        </div>
      </div>
    </Layout>
  );
}
