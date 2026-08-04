import { useCallback, useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { Play, TrendingUp, Activity, Clock, RotateCcw, Save, CheckCircle2 } from "lucide-react";
import Layout from "../components/Layout";
import JobTracker from "../components/JobTracker";
import PlotlyEmbed from "../components/PlotlyEmbed";
import StatCard from "../components/StatCard";
import EmptyState from "../components/ui/EmptyState";
import FormField from "../components/ui/FormField";
import { startSimulation, getSimConfig, saveSimConfig, cancelAllJobs } from "../api/client";
import { useAppState } from "../contexts/AppContext";
import type { SimulationParams, SimulationResult } from "../types/api";

const DEFAULTS: SimulationParams = {
  n_clients:   2000,
  n_merchants: 300,
  n_banks:     20,
  n_mules:     60,
  n_steps:     720,
  max_slots:   6,
  seed:        1000,
  fraud_probas: null,
};

const SCENARIO_COLORS: Record<string, string> = {
  ATO:       "bg-accent-fraud",
  REFUND:    "bg-accent-blue",
  FAKE_CRED: "bg-accent-green",
  SPLIT_DEP: "bg-accent-purple",
  SMURFING:  "bg-accent-amber",
};

export default function SimulationPage() {
  const location = useLocation();
  const preloaded = (location.state as { params?: SimulationParams } | null)?.params;

  const { simJobId, simResult, setSimJobId, setSimResult } = useAppState();

  const [params, setParams]   = useState<SimulationParams>(() => preloaded ? { ...preloaded, fraud_probas: null } : DEFAULTS);
  const [fromHistory]         = useState<boolean>(!!preloaded);
  const [loading, setLoading] = useState(false);
  const [hasError, setHasError] = useState(false);
  const [saved, setSaved]     = useState(false);

  // Chargement de la config sauvegardée au montage (sauf si on vient de l'historique)
  useEffect(() => {
    if (!preloaded) {
      getSimConfig()
        .then((cfg) => setParams((p) => ({ ...p, ...cfg, fraud_probas: null })))
        .catch(() => {});
    }
  }, [preloaded]);

  const set = useCallback((name: string, value: number) => {
    setSaved(false);
    setParams((p) => ({ ...p, [name]: value }));
  }, []);

  const handleSave = useCallback(async () => {
    try {
      await saveSimConfig(params);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch { /* ignore */ }
  }, [params]);

  const launch = useCallback(async () => {
    setLoading(true);
    setHasError(false);
    setSimResult(null);
    try {
      const { job_id } = await startSimulation(params);
      setSimJobId(job_id);
    } finally {
      setLoading(false);
    }
  }, [params, setSimJobId, setSimResult]);

  const onDone = useCallback((r: Record<string, unknown>) => {
    setSimResult(r as unknown as SimulationResult);
  }, [setSimResult]);

  const onError = useCallback(() => setHasError(true), []);

  const jobId  = simJobId;
  const result = simResult;

  const canLaunch = !loading && (jobId === null || result !== null || hasError);

  return (
    <Layout
      title="Simulation MoMTSim"
      subtitle="Génération du rawLog_torch.parquet — section 3.1 du mémoire"
    >
      {fromHistory && (
        <div className="mb-4 flex items-center gap-2 px-3 py-2 rounded-lg bg-accent-blue/10 border border-accent-blue/25 text-xs text-accent-blue">
          <RotateCcw className="w-3.5 h-3.5 flex-shrink-0" aria-hidden="true" />
          Paramètres rechargés depuis l'historique — modifiez n_steps pour prolonger la simulation, puis relancez.
        </div>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
        {/* ── Config panel ──────────────────────────────────────────── */}
        <div className="xl:col-span-1 space-y-4">
          <div className="card">
            <h2 className="section-title mb-0.5">Paramètres</h2>
            <p className="text-xs text-text-muted mb-4">Population &amp; horizon temporel</p>
            <div className="grid grid-cols-2 gap-3">
              <FormField label="Clients"       name="n_clients"   value={params.n_clients}   onChange={set} min={100} />
              <FormField label="Marchands"     name="n_merchants" value={params.n_merchants} onChange={set} min={10} />
              <FormField label="Banques"       name="n_banks"     value={params.n_banks}     onChange={set} min={1} />
              <FormField label="Mules"         name="n_mules"     value={params.n_mules}     onChange={set} min={0} />
              <FormField label="Steps (h)"     name="n_steps"     value={params.n_steps}     onChange={set} min={24} max={8760} hint="720=30j · 1080=45j · 1440=60j" />
              <FormField label="Max slots"     name="max_slots"   value={params.max_slots}   onChange={set} min={1}  max={200} hint="tx/client/h" />
              <div className="col-span-2">
                <FormField label="Seed aléatoire" name="seed" value={params.seed} onChange={set} min={0} />
              </div>
            </div>
          </div>

          {/* Memo */}
          <div className="card-sm text-xs text-text-dim font-mono space-y-1">
            <p className="text-2xs text-text-muted uppercase tracking-widest mb-2 font-sans font-medium">
              Rappel mémoire
            </p>
            <p>720 steps = 30 jours (1 step = 1h)</p>
            <p>Probas chargées depuis calibrated_probas.json</p>
            <p className="pt-1 border-t border-border-subtle mt-1 text-text-muted">Float agent (§3.2.4)</p>
            <p>Petit agent : 100k–500k FCFA · 60 %</p>
            <p>Agent moyen : 500k–2M FCFA · 30 %</p>
            <p>Grand agent : 2M–10M FCFA · 10 %</p>
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
                  <Play className="w-4 h-4" aria-hidden="true" />
                  Lancer
                </>
              )}
            </button>
            <button
              className={[
                "btn-secondary flex items-center gap-1.5 px-3",
                saved ? "text-accent-green border-accent-green/30" : "",
              ].join(" ")}
              onClick={handleSave}
              title="Sauvegarder la configuration dans sim_config.json"
              aria-label="Sauvegarder la configuration"
            >
              {saved
                ? <CheckCircle2 className="w-4 h-4" aria-hidden="true" />
                : <Save className="w-4 h-4" aria-hidden="true" />
              }
            </button>
          </div>

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
                  label="Transactions"
                  value={result.n_transactions.toLocaleString("fr-FR")}
                  icon={Activity}
                  color="blue"
                />
                <StatCard
                  label="Taux de fraude"
                  value={(result.fraud_rate * 100).toFixed(2)}
                  unit="%"
                  icon={TrendingUp}
                  color={result.fraud_rate > 0.25 ? "red" : "green"}
                />
                <StatCard
                  label="Steps simulés"
                  value={result.steps_run}
                  unit="h"
                  icon={Clock}
                />
              </div>

              {/* Scenario breakdown */}
              {Object.keys(result.fraud_by_scenario).length > 0 && (
                <div className="card">
                  <h3 className="card-title mb-3">Répartition par scénario</h3>
                  <div className="space-y-2.5">
                    {Object.entries(result.fraud_by_scenario).map(([sc, pct]) => (
                      <div key={sc} className="flex items-center gap-3">
                        <span className="font-mono text-xs text-text-muted w-24 flex-shrink-0">{sc}</span>
                        <div className="flex-1 bg-bg-secondary rounded-full h-1 overflow-hidden" role="presentation">
                          <div
                            className={`h-1 rounded-full transition-all duration-500 ${SCENARIO_COLORS[sc] ?? "bg-accent-blue"}`}
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

              {/* Résumé langage naturel */}
              {result.plain_summary && (
                <div className="card border-accent-blue/20 bg-accent-blue/5">
                  <p className="text-xs text-text-muted leading-relaxed">{result.plain_summary}</p>
                </div>
              )}

              {/* Plotly charts — vue globale */}
              {result.charts.volume_par_action && (
                <PlotlyEmbed html={result.charts.volume_par_action} title="Volume par action et par step" />
              )}
              {result.charts.nrmse_heatmap && (
                <PlotlyEmbed html={result.charts.nrmse_heatmap} title="NRMSE par action × estimateur — section 3.1.3" height={340} />
              )}
              {result.charts.repartition_fraude && (
                <PlotlyEmbed html={result.charts.repartition_fraude} title="Répartition des scénarios de fraude" height={360} />
              )}
              {result.charts.timeline_fraude && (
                <PlotlyEmbed html={result.charts.timeline_fraude} title="Timeline des fraudes (720 steps = 30 jours)" />
              )}
              {result.charts.fraudster_summary && (
                <PlotlyEmbed html={result.charts.fraudster_summary} title="Synthèse par scénario — section 3.2" height={420} />
              )}

              {/* Conformité par scénario */}
              {result.charts.ato_exfiltration && (
                <PlotlyEmbed html={result.charts.ato_exfiltration} title="ATO — fenêtre d'exfiltration (§3.2.1)" height={400} />
              )}
              {result.charts.refund_delays && (
                <PlotlyEmbed html={result.charts.refund_delays} title="REFUND — distribution des délais (§3.2.2)" height={400} />
              )}
              {result.charts.fake_cred_dormance && (
                <PlotlyEmbed html={result.charts.fake_cred_dormance} title="FAKE_CRED — périodes de dormance (§3.2.3)" height={400} />
              )}
              {result.charts.split_deposit_var && (
                <PlotlyEmbed html={result.charts.split_deposit_var} title="SPLIT_DEP — variance intra-opération (§3.2.4)" height={400} />
              )}
              {result.charts.smurfing_periodicity && (
                <PlotlyEmbed html={result.charts.smurfing_periodicity} title="SMURFING — périodicité inter-opérations (§3.2.5)" height={400} />
              )}
              {result.charts.smurfing_sankey && (
                <PlotlyEmbed html={result.charts.smurfing_sankey} title="SMURFING — réseau Sankey émetteur→mule→récepteur" height={520} />
              )}
            </div>
          ) : (
            <EmptyState
              icon={Play}
              title="Aucun résultat disponible"
              description="Configurez les paramètres et lancez la simulation. Les probabilités calibrées seront utilisées automatiquement."
            />
          )}
        </div>
      </div>
    </Layout>
  );
}
