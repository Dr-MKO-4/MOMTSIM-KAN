import { useCallback, useEffect, useState } from "react";
import { BarChart3, Activity, TrendingDown, CheckCircle2, XCircle, Save } from "lucide-react";
import Layout from "../components/Layout";
import JobTracker from "../components/JobTracker";
import StatCard from "../components/StatCard";
import EmptyState from "../components/ui/EmptyState";
import FormField from "../components/ui/FormField";
import { startCalibration, getCalibConfig, saveCalibConfig, cancelAllJobs } from "../api/client";
import { useAppState } from "../contexts/AppContext";
import type { CalibrationParams, CalibrationResult } from "../types/api";

const DEFAULTS: CalibrationParams = {
  n_clients:       500,
  n_merchants:     100,
  n_banks:         10,
  n_mules:         300,
  max_slots:       50,
  target_mid:      0.23,
  n_steps:         720,
  n_bins:          30,
  n_seeds_per_eval: 3,
  maxiter:         30,
  lr:              0.05,
  spsa_c:          0.02,
};

const SCENARIO_KEYS = ["ato", "refund", "fake_credentials", "split_deposit", "smurfing_freq_mult"] as const;

const SCENARIO_LABELS: Record<string, string> = {
  ato:                "ATO — p(fraude)",
  refund:             "REFUND — p(fraude)",
  fake_credentials:   "FAKE_CRED — p(fraude)",
  split_deposit:      "SPLIT_DEP — p(fraude)",
  smurfing_freq_mult: "SMURFING — freq_mult",
};

const SCENARIO_BAR_SCALE: Record<string, number> = {
  smurfing_freq_mult: 10,
};

export default function CalibrationPage() {
  const { calibJobId, calibResult, setCalibJobId, setCalibResult } = useAppState();

  const [params, setParams]   = useState<CalibrationParams>(DEFAULTS);
  const [loading, setLoading] = useState(false);
  const [hasError, setHasError] = useState(false);
  const [saved, setSaved]     = useState(false);

  const jobId  = calibJobId;
  const result = calibResult;

  // Chargement de la config sauvegardée au montage
  // n_mules et max_slots viennent automatiquement de sim_config.json (via le backend)
  useEffect(() => {
    getCalibConfig()
      .then((cfg) => setParams((p) => ({ ...p, ...cfg })))
      .catch(() => {});
  }, []);

  const set = useCallback((name: string, value: number) => {
    setSaved(false);
    setParams((p) => ({ ...p, [name]: value }));
  }, []);

  const handleSave = useCallback(async () => {
    try {
      await saveCalibConfig(params);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch { /* ignore */ }
  }, [params]);

  const launch = useCallback(async () => {
    setLoading(true);
    setHasError(false);
    setCalibResult(null);
    try {
      const { job_id } = await startCalibration(params);
      setCalibJobId(job_id);
    } finally {
      setLoading(false);
    }
  }, [params, setCalibJobId, setCalibResult]);

  const onDone = useCallback((r: Record<string, unknown>) => {
    setCalibResult(r as unknown as CalibrationResult);
  }, [setCalibResult]);

  const onError = useCallback(() => setHasError(true), []);

  const canLaunch = !loading && (jobId === null || result !== null || hasError);
  const totalRuns  = params.maxiter * 2 * params.n_seeds_per_eval;

  return (
    <Layout
      title="Calibration SSE/SPSA"
      subtitle="θ* = argmin Σ_c Σ_t (Dr − Ds)² — section 3.1.3 du mémoire"
    >
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
        {/* ── Config panel ──────────────────────────────────────────── */}
        <div className="xl:col-span-1 space-y-4">
          <div className="card">
            <h2 className="section-title mb-0.5">Paramètres SPSA</h2>
            <p className="text-xs text-text-muted mb-4">Population réduite pour la vitesse de convergence</p>
            <div className="grid grid-cols-2 gap-3">
              <FormField label="Clients"       name="n_clients"        value={params.n_clients}        onChange={set} min={50} />
              <FormField label="Marchands"     name="n_merchants"      value={params.n_merchants}      onChange={set} min={10} />
              <FormField label="Banques"       name="n_banks"          value={params.n_banks}          onChange={set} min={1} />
              <FormField label="Mules"         name="n_mules"          value={params.n_mules}          onChange={set} min={0} hint="← depuis sim_config.json" />
              <FormField label="Max slots"     name="max_slots"        value={params.max_slots}        onChange={set} min={1} hint="← depuis sim_config.json" />
              <FormField label="target_mid"    name="target_mid"       value={params.target_mid}       onChange={set} min={0.1} max={0.5} isFloat hint="Taux de fraude cible" />
              <FormField label="n_steps"       name="n_steps"          value={params.n_steps}          onChange={set} min={24} />
              <FormField label="n_bins"        name="n_bins"           value={params.n_bins}           onChange={set} min={5} />
              <FormField label="seeds / eval"  name="n_seeds_per_eval" value={params.n_seeds_per_eval} onChange={set} min={1} />
              <FormField label="maxiter"       name="maxiter"          value={params.maxiter}          onChange={set} min={5} max={200} />
              <FormField label="lr"            name="lr"               value={params.lr}               onChange={set} min={0.001} isFloat />
              <div className="col-span-2">
                <FormField label="spsa_c"      name="spsa_c"           value={params.spsa_c}           onChange={set} min={0.001} isFloat />
              </div>
            </div>
          </div>

          {/* Formula memo */}
          <div className="card-sm text-xs font-mono space-y-1">
            <p className="text-2xs text-text-muted uppercase tracking-widest mb-2 font-sans font-medium">Ma contribution — §3.1.4</p>
            <p className="text-text-muted leading-relaxed">θ* = argmin sse(θ)</p>
            <p className="text-text-dim">sse = Σ_c Σ_t (Dr − D̄s)²</p>
            <p className="text-text-dim">c ∈ {"{ATO, REFUND, FAKE_CRED,"}</p>
            <p className="text-text-dim pl-4">{"SPLIT_DEP, SMURFING}"}</p>
            <p className="text-text-dim mt-1">Dr(c,t) = N_lég(t)·r / (1−r)·5</p>
            <p className="text-text-dim">D̄s = moyenne sur {params.n_seeds_per_eval} seeds</p>
            <p className="text-text-dim mt-1">SPSA : 2 éval/iter (Spall 1992)</p>
            <p className="text-accent-blue mt-1">≈ {totalRuns} simulations</p>
          </div>

          <div className="flex gap-2">
            <button
              className="btn-primary flex-1"
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
                  <BarChart3 className="w-4 h-4" aria-hidden="true" />
                  Calibrer
                </>
              )}
            </button>
            <button
              className={[
                "btn-secondary flex items-center gap-1.5 px-3",
                saved ? "text-accent-green border-accent-green/30" : "",
              ].join(" ")}
              onClick={handleSave}
              title="Sauvegarder la configuration dans calib_config.json"
              aria-label="Sauvegarder la configuration SPSA"
            >
              {saved
                ? <CheckCircle2 className="w-4 h-4" aria-hidden="true" />
                : <Save className="w-4 h-4" aria-hidden="true" />
              }
            </button>
          </div>

          <p className="caption text-center">
            Peut prendre plusieurs minutes selon maxiter et n_clients.
          </p>

          <JobTracker
            jobId={jobId}
            onDone={onDone}
            onError={onError}
            onStop={() => { cancelAllJobs().catch(() => {}); }}
            onRestart={launch}
          />
        </div>

        {/* ── Results panel ─────────────────────────────────────────── */}
        <div className="xl:col-span-2 space-y-5">
          {result ? (
            <div className="space-y-5 animate-fade-in">
              {/* KPI */}
              <div className="grid grid-cols-3 gap-3">
                <StatCard
                  label="SSE normalisé"
                  value={result.sse_final < 0.01
                    ? result.sse_final.toExponential(2)
                    : result.sse_final.toFixed(4)}
                  icon={TrendingDown}
                  color={result.converged ? "green" : "amber"}
                  description={result.converged ? "< 1.0 ✓" : "≥ 1.0"}
                />
                <StatCard
                  label="Itérations"
                  value={result.history.length}
                  icon={BarChart3}
                  color="blue"
                />
                <StatCard
                  label="Convergence"
                  value={result.converged ? "Oui" : "Non"}
                  icon={result.converged ? CheckCircle2 : XCircle}
                  color={result.converged ? "green" : "red"}
                />
              </div>

              {/* Optimal probas */}
              <div className="card">
                <div className="flex items-center gap-2 mb-3">
                  <h3 className="card-title">Probabilités optimales θ*</h3>
                  <span className="badge-green">Sauvegardées</span>
                </div>
                <div className="space-y-3">
                  {SCENARIO_KEYS.map((k) => {
                    const v     = result.probas[k] ?? 0;
                    const scale = SCENARIO_BAR_SCALE[k] ?? 1;
                    const pct   = Math.min(v * 100 * scale, 100);
                    return (
                      <div key={k} className="flex items-center gap-3">
                        <span className="font-mono text-xs text-text-muted w-40 flex-shrink-0 truncate">
                          {SCENARIO_LABELS[k] ?? k}
                        </span>
                        <div
                          className="flex-1 bg-bg-secondary rounded-full h-1 overflow-hidden"
                          role="progressbar"
                          aria-valuenow={pct}
                          aria-valuemin={0}
                          aria-valuemax={100}
                          aria-label={`${SCENARIO_LABELS[k] ?? k} : ${v.toFixed(4)}`}
                        >
                          <div
                            className="bg-accent-blue h-1 rounded-full transition-all duration-700"
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                        <span className="font-mono text-xs text-accent-blue w-16 text-right flex-shrink-0">
                          {v.toFixed(4)}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* SSE history */}
              <div className="card">
                <h3 className="card-title mb-0.5">Historique SSE (10 dernières itérations)</h3>
                <p className="text-xs text-text-muted mb-3">
                  {result.history.length} itérations au total
                </p>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs font-mono" aria-label="Historique de convergence SSE">
                    <thead>
                      <tr>
                        <th className="table-th">iter</th>
                        <th className="table-th text-right">SSE</th>
                        <th className="table-th">θ (extrait)</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.history.slice(-10).map((h) => {
                        const isBest = h.sse === result.sse_final;
                        return (
                          <tr key={h.iter} className="hover:bg-bg-hover transition-colors duration-100">
                            <td className="table-td text-text-dim">{h.iter}</td>
                            <td className={`table-td text-right font-medium ${
                              isBest ? "text-accent-green" : "text-text-muted"
                            }`}>
                              {h.sse.toFixed(1)}
                              {isBest && <span className="ml-1.5 badge-green">best</span>}
                            </td>
                            <td className="table-td text-text-dim truncate max-w-[200px]">
                              [{h.theta.slice(0, 3).map((v) => v.toFixed(4)).join(", ")}
                              {h.theta.length > 3 ? "…" : "]"}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                  {result.history.length > 10 && (
                    <p className="text-2xs text-text-dim mt-2">
                      Affichage des 10 dernières itérations sur {result.history.length}
                    </p>
                  )}
                </div>
              </div>
            </div>
          ) : (
            <EmptyState
              icon={BarChart3}
              title="Aucun résultat disponible"
              description="Calibrez les probabilités de fraude par SPSA. Les résultats sont sauvegardés dans calibrated_probas.json et utilisés automatiquement par la simulation."
            />
          )}
        </div>
      </div>
    </Layout>
  );
}
