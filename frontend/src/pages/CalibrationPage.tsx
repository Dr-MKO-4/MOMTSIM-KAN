import { useState } from "react";
import Layout from "../components/Layout";
import JobTracker from "../components/JobTracker";
import StatCard from "../components/StatCard";
import { startCalibration } from "../api/client";
import type { CalibrationParams, CalibrationResult } from "../types/api";

const DEFAULTS: CalibrationParams = {
  n_clients: 500,
  n_merchants: 100,
  n_banks: 10,
  n_mules: 30,
  target_mid: 0.23,
  n_steps: 720,
  n_bins: 30,
  n_seeds_per_eval: 3,
  maxiter: 25,
  lr: 0.05,
  spsa_c: 0.02,
};

function Field({
  label, name, value, onChange, min, max, step = 1, isFloat = false,
}: {
  label: string; name: string; value: number; onChange: (n: string, v: number) => void;
  min?: number; max?: number; step?: number; isFloat?: boolean;
}) {
  return (
    <div>
      <label className="label">{label}</label>
      <input
        type="number"
        className="input"
        value={value}
        min={min}
        max={max}
        step={isFloat ? 0.001 : step}
        onChange={(e) => onChange(name, parseFloat(e.target.value))}
      />
    </div>
  );
}

const SCENARIO_KEYS = ["ato", "refund", "fake_credentials", "split_deposit", "smurfing_freq_mult"];
const SCENARIO_LABELS: Record<string, string> = {
  ato: "ATO p(fraude)", refund: "REFUND p(fraude)",
  fake_credentials: "FAKE_CRED p(fraude)", split_deposit: "SPLIT_DEP p(fraude)",
  smurfing_freq_mult: "SMURFING freq_mult",
};

export default function CalibrationPage() {
  const [params, setParams] = useState<CalibrationParams>(DEFAULTS);
  const [jobId, setJobId] = useState<string | null>(null);
  const [result, setResult] = useState<CalibrationResult | null>(null);
  const [loading, setLoading] = useState(false);

  const set = (name: string, value: number) =>
    setParams((p) => ({ ...p, [name]: value }));

  const launch = async () => {
    setLoading(true);
    setResult(null);
    try {
      const { job_id } = await startCalibration(params);
      setJobId(job_id);
    } finally {
      setLoading(false);
    }
  };

  const onDone = (r: Record<string, unknown>) => {
    setResult(r as unknown as CalibrationResult);
  };

  return (
    <Layout
      title="Calibration SSE/SPSA"
      subtitle="θ* = argmin Σ_c Σ_t (Dr − Ds)² — section 3.1.3 du mémoire"
    >
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        {/* Config */}
        <div className="xl:col-span-1 space-y-4">
          <div className="card">
            <h2 className="section-title">Paramètres SPSA</h2>
            <p className="section-subtitle">Population réduite pour la vitesse</p>
            <div className="grid grid-cols-2 gap-3 mt-2">
              <Field label="Clients" name="n_clients" value={params.n_clients} onChange={set} min={50} />
              <Field label="Marchands" name="n_merchants" value={params.n_merchants} onChange={set} min={10} />
              <Field label="Banques" name="n_banks" value={params.n_banks} onChange={set} min={1} />
              <Field label="Mules" name="n_mules" value={params.n_mules} onChange={set} min={0} />
              <Field label="target_mid" name="target_mid" value={params.target_mid} onChange={set} min={0.1} max={0.5} isFloat />
              <Field label="n_steps" name="n_steps" value={params.n_steps} onChange={set} min={24} />
              <Field label="n_bins" name="n_bins" value={params.n_bins} onChange={set} min={5} />
              <Field label="seeds/eval" name="n_seeds_per_eval" value={params.n_seeds_per_eval} onChange={set} min={1} />
              <Field label="maxiter" name="maxiter" value={params.maxiter} onChange={set} min={5} max={200} />
              <Field label="lr" name="lr" value={params.lr} onChange={set} min={0.001} isFloat />
              <Field label="spsa_c" name="spsa_c" value={params.spsa_c} onChange={set} min={0.001} isFloat />
            </div>
          </div>

          <div className="card text-xs text-text-muted font-mono space-y-1">
            <p className="text-text-dim uppercase text-2xs tracking-widest mb-2">Formule</p>
            <p>θ* = argmin_θ Σ_c Σ_t (Dr(c,t) − Ds(c,t;θ))²</p>
            <p className="text-text-dim mt-1">2 évals / iter (SPSA)</p>
            <p className="text-text-dim">~{params.maxiter * 2 * params.n_seeds_per_eval} runs total</p>
          </div>

          <button
            className="btn-primary w-full text-sm"
            onClick={launch}
            disabled={loading || (jobId !== null && result === null)}
          >
            {loading ? "Lancement…" : "↺ Calibrer les probabilités"}
          </button>

          <p className="text-xs text-text-dim text-center">
            Peut prendre plusieurs minutes selon maxiter et n_clients.
          </p>

          <JobTracker jobId={jobId} onDone={onDone} onError={() => {}} />
        </div>

        {/* Résultats */}
        <div className="xl:col-span-2 space-y-6">
          {result ? (
            <>
              <div className="grid grid-cols-3 gap-4">
                <StatCard label="SSE final" value={result.sse_final.toFixed(1)} color={result.converged ? "green" : "amber"} />
                <StatCard label="Iterations" value={result.history.length} color="blue" />
                <StatCard label="Convergé" value={result.converged ? "Oui" : "Non"} color={result.converged ? "green" : "red"} />
              </div>

              {/* Probas calibrées */}
              <div className="card">
                <h3 className="text-sm font-medium text-text-primary mb-3">
                  Probabilités optimales θ* <span className="badge-green ml-2">Sauvegardées</span>
                </h3>
                <div className="space-y-3">
                  {SCENARIO_KEYS.map((k) => {
                    const v = result.probas[k] ?? 0;
                    return (
                      <div key={k} className="flex items-center gap-3">
                        <span className="font-mono text-xs text-text-muted w-36 flex-shrink-0">
                          {SCENARIO_LABELS[k] ?? k}
                        </span>
                        <div className="flex-1 bg-bg-secondary rounded-full h-1.5">
                          <div
                            className="bg-accent-blue h-1.5 rounded-full"
                            style={{ width: `${Math.min(v * 100 * (k === "smurfing_freq_mult" ? 10 : 1), 100)}%` }}
                          />
                        </div>
                        <span className="font-mono text-xs text-accent-blue w-16 text-right">
                          {v.toFixed(4)}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>

              {/* Historique SSE */}
              <div className="card">
                <h3 className="text-sm font-medium text-text-primary mb-3">Convergence SSE</h3>
                <div className="overflow-x-auto">
                  <table className="w-full text-xs font-mono">
                    <thead>
                      <tr className="text-text-dim">
                        <th className="text-left py-1 pr-4">iter</th>
                        <th className="text-right py-1 pr-4">SSE</th>
                        <th className="text-left py-1">θ</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.history.slice(-10).map((h) => (
                        <tr key={h.iter} className="border-t border-border/50">
                          <td className="py-1 pr-4 text-text-dim">{h.iter}</td>
                          <td className={`py-1 pr-4 text-right ${h.sse === result.sse_final ? "text-accent-green font-bold" : "text-text-muted"}`}>
                            {h.sse.toFixed(1)}
                          </td>
                          <td className="py-1 text-text-dim">
                            [{h.theta.map((v) => v.toFixed(4)).join(", ")}]
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  {result.history.length > 10 && (
                    <p className="text-2xs text-text-dim mt-1">
                      (10 dernières itérations sur {result.history.length})
                    </p>
                  )}
                </div>
              </div>
            </>
          ) : (
            <div className="card flex flex-col items-center justify-center min-h-[300px] text-center">
              <p className="text-4xl mb-4 text-text-dim font-mono">θ*</p>
              <p className="text-sm text-text-muted">
                Calibrez les probabilités de fraude par SPSA.
              </p>
              <p className="text-xs text-text-dim mt-1">
                Les probas sont sauvegardées dans calibrated_probas.json
                et utilisées automatiquement par la simulation.
              </p>
            </div>
          )}
        </div>
      </div>
    </Layout>
  );
}
