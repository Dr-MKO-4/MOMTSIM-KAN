import { useState } from "react";
import Layout from "../components/Layout";
import JobTracker from "../components/JobTracker";
import PlotlyEmbed from "../components/PlotlyEmbed";
import StatCard from "../components/StatCard";
import { startSimulation } from "../api/client";
import type { SimulationParams, SimulationResult } from "../types/api";

const DEFAULTS: SimulationParams = {
  n_clients: 2000,
  n_merchants: 300,
  n_banks: 20,
  n_mules: 60,
  n_steps: 720,
  max_slots: 6,
  seed: 1000,
  fraud_probas: null,
};

function Field({
  label, name, value, onChange, min, max, step = 1, type = "number",
}: {
  label: string; name: string; value: number; onChange: (n: string, v: number) => void;
  min?: number; max?: number; step?: number; type?: string;
}) {
  return (
    <div>
      <label className="label">{label}</label>
      <input
        type={type}
        className="input"
        value={value}
        min={min}
        max={max}
        step={step}
        onChange={(e) => onChange(name, parseFloat(e.target.value))}
      />
    </div>
  );
}

export default function SimulationPage() {
  const [params, setParams] = useState<SimulationParams>(DEFAULTS);
  const [jobId, setJobId] = useState<string | null>(null);
  const [result, setResult] = useState<SimulationResult | null>(null);
  const [loading, setLoading] = useState(false);

  const set = (name: string, value: number) =>
    setParams((p) => ({ ...p, [name]: value }));

  const launch = async () => {
    setLoading(true);
    setResult(null);
    try {
      const { job_id } = await startSimulation(params);
      setJobId(job_id);
    } finally {
      setLoading(false);
    }
  };

  const onDone = (r: Record<string, unknown>) => {
    setResult(r as unknown as SimulationResult);
  };

  return (
    <Layout
      title="Simulation MoMTSim"
      subtitle="Génération du rawLog_torch.csv — section 3.1 du mémoire"
    >
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        {/* Panneau config */}
        <div className="xl:col-span-1 space-y-4">
          <div className="card">
            <h2 className="section-title">Paramètres</h2>
            <p className="section-subtitle">Population & horizon temporel</p>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Clients" name="n_clients" value={params.n_clients} onChange={set} min={100} max={10000} />
              <Field label="Marchands" name="n_merchants" value={params.n_merchants} onChange={set} min={10} />
              <Field label="Banques" name="n_banks" value={params.n_banks} onChange={set} min={1} />
              <Field label="Mules" name="n_mules" value={params.n_mules} onChange={set} min={0} />
              <Field label="Steps (heures)" name="n_steps" value={params.n_steps} onChange={set} min={24} max={8760} />
              <Field label="Max slots/step" name="max_slots" value={params.max_slots} onChange={set} min={1} max={20} />
              <Field label="Seed" name="seed" value={params.seed} onChange={set} min={0} />
            </div>
          </div>

          <div className="card text-xs text-text-muted font-mono space-y-1">
            <p className="text-text-dim uppercase text-2xs tracking-widest mb-2">Rappel mémoire</p>
            <p>N_STEPS = 720 → 30 jours</p>
            <p>1 step = 1 heure</p>
            <p>Probas : chargées depuis calibrated_probas.json</p>
          </div>

          <button
            className="btn-primary w-full text-sm"
            onClick={launch}
            disabled={loading || jobId !== null && result === null}
          >
            {loading ? "Lancement…" : "▶ Lancer la simulation"}
          </button>

          <JobTracker jobId={jobId} onDone={onDone} onError={() => {}} />
        </div>

        {/* Résultats */}
        <div className="xl:col-span-2 space-y-6">
          {result ? (
            <>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
                <StatCard
                  label="Transactions"
                  value={result.n_transactions.toLocaleString("fr-FR")}
                  color="blue"
                />
                <StatCard
                  label="Taux de fraude"
                  value={(result.fraud_rate * 100).toFixed(2)}
                  unit="%"
                  color={result.fraud_rate > 0.25 ? "red" : "green"}
                />
                <StatCard
                  label="Steps simulés"
                  value={result.steps_run}
                  unit="h"
                />
              </div>

              {/* Répartition par scénario */}
              {Object.keys(result.fraud_by_scenario).length > 0 && (
                <div className="card">
                  <h3 className="text-sm font-medium text-text-primary mb-3">
                    Répartition des fraudes
                  </h3>
                  <div className="space-y-2">
                    {Object.entries(result.fraud_by_scenario).map(([sc, pct]) => (
                      <div key={sc} className="flex items-center gap-3">
                        <span className="font-mono text-xs text-text-muted w-24 flex-shrink-0">
                          {sc}
                        </span>
                        <div className="flex-1 bg-bg-secondary rounded-full h-1.5">
                          <div
                            className="bg-accent-fraud h-1.5 rounded-full"
                            style={{ width: `${(pct * 100).toFixed(1)}%` }}
                          />
                        </div>
                        <span className="font-mono text-xs text-text-muted w-12 text-right">
                          {(pct * 100).toFixed(1)}%
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Graphiques Plotly */}
              {result.charts.volume_par_action && (
                <PlotlyEmbed html={result.charts.volume_par_action} title="Volume par action" />
              )}
              {result.charts.repartition_fraude && (
                <PlotlyEmbed html={result.charts.repartition_fraude} title="Répartition des scénarios" height={380} />
              )}
              {result.charts.timeline_fraude && (
                <PlotlyEmbed html={result.charts.timeline_fraude} title="Timeline fraude" />
              )}
            </>
          ) : (
            <div className="card flex flex-col items-center justify-center min-h-[300px] text-center">
              <p className="text-4xl mb-4 text-text-dim">▷</p>
              <p className="text-sm text-text-muted">
                Configurez les paramètres et lancez la simulation.
              </p>
              <p className="text-xs text-text-dim mt-1">
                Les probabilités calibrées seront utilisées automatiquement.
              </p>
            </div>
          )}
        </div>
      </div>
    </Layout>
  );
}
