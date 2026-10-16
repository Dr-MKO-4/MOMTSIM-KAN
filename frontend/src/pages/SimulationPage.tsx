import { useCallback, useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { Play, TrendingUp, Activity, Clock, RotateCcw, Save, CheckCircle2, Timer } from "lucide-react";
import Layout from "../components/Layout";
import JobTracker, { formatDuration } from "../components/JobTracker";
import PlotlyEmbed from "../components/PlotlyEmbed";
import StatCard from "../components/StatCard";
import VerdictPanel from "../components/VerdictPanel";
import EmptyState from "../components/ui/EmptyState";
import FormField from "../components/ui/FormField";
import Toggle from "../components/ui/Toggle";
import CommandBlock from "../components/ui/CommandBlock";
import ProgressBar from "../components/ui/ProgressBar";
import { startSimulation, getSimConfig, saveSimConfig } from "../api/client";
import { useAppState } from "../contexts/AppContext";
import type { SimulationParams, SimulationResult, Job } from "../types/api";

/* Régimes d'exécution du mémoire (section 3.1.2) */
const PRESETS: { key: string; label: string; hint: string; cli?: string; p: Omit<SimulationParams, "fraud_probas"> }[] = [
  { key: "essai", label: "Essai rapide", hint: "20 000 clients, 10 jours, proportions du mémoire",
    p: { n_clients: 20000, n_merchants: 480, n_banks: 8, n_mules: 84, n_steps: 240, max_slots: 3, seed: 1000, volume_scale: null, volume_follow: false } },
  { key: "calibration", label: "Calibration", hint: "Régime de calibration SPSA, 30 jours",
    p: { n_clients: 2000, n_merchants: 200, n_banks: 8, n_mules: 800, n_steps: 720, max_slots: 50, seed: 1000, volume_scale: 1.0, volume_follow: false } },
  { key: "entrainement", label: "Entraînement", hint: "500 000 clients, 60 jours, graine 1000", cli: "entrainement",
    p: { n_clients: 500000, n_merchants: 12000, n_banks: 8, n_mules: 2100, n_steps: 1440, max_slots: 3, seed: 1000, volume_scale: null, volume_follow: false } },
  { key: "validation", label: "Validation", hint: "150 000 clients, 60 jours, graine 1001", cli: "validation",
    p: { n_clients: 150000, n_merchants: 3600, n_banks: 8, n_mules: 630, n_steps: 1440, max_slots: 3, seed: 1001, volume_scale: null, volume_follow: false } },
  { key: "test", label: "Test", hint: "150 000 clients, 60 jours, graine 1002", cli: "test",
    p: { n_clients: 150000, n_merchants: 3600, n_banks: 8, n_mules: 630, n_steps: 1440, max_slots: 3, seed: 1002, volume_scale: null, volume_follow: false } },
];

const DEFAULTS: SimulationParams = { ...PRESETS[0].p, fraud_probas: null };

const SCENARIO_COLORS: Record<string, "red" | "brand" | "green" | "amber" | "gray"> = {
  ATO: "red", REFUND: "brand", FAKE_CRED: "green", SPLIT_DEP: "brand", SMURFING: "amber",
};

const CHARTS: { key: string; title: string; height?: number }[] = [
  { key: "volume_par_action",    title: "Volume par action et par pas" },
  { key: "nrmse_heatmap",        title: "NRMSE par action et estimateur", height: 340 },
  { key: "repartition_fraude",   title: "Répartition des scénarios de fraude", height: 360 },
  { key: "timeline_fraude",      title: "Chronologie des fraudes" },
  { key: "fraudster_summary",    title: "Synthèse par scénario (section 3.3)", height: 420 },
  { key: "ato_exfiltration",     title: "ATO : fenêtre d'exfiltration", height: 400 },
  { key: "refund_delays",        title: "REFUND : délais de remboursement", height: 400 },
  { key: "fake_cred_dormance",   title: "FAKE_CRED : périodes de dormance", height: 400 },
  { key: "split_deposit_var",    title: "SPLIT_DEP : variance intra-opération", height: 400 },
  { key: "smurfing_periodicity", title: "SMURFING : périodicité des opérations", height: 400 },
  { key: "smurfing_sankey",      title: "SMURFING : émetteur → mules → récepteur", height: 520 },
];

export default function SimulationPage() {
  const location = useLocation();
  const preloaded = (location.state as { params?: SimulationParams } | null)?.params;

  const { simJobId, simResult, setSimJobId, setSimResult } = useAppState();

  const [params, setParams]     = useState<SimulationParams>(() => preloaded ? { ...preloaded, fraud_probas: null } : DEFAULTS);
  const [fromHistory]           = useState<boolean>(!!preloaded);
  const [preset, setPreset]     = useState<string | null>(null);
  const [loading, setLoading]   = useState(false);
  const [hasError, setHasError] = useState(false);
  const [saved, setSaved]       = useState(false);
  const [jobActive, setJobActive] = useState(false);

  useEffect(() => {
    if (!preloaded) {
      getSimConfig().then((cfg) => setParams((p) => ({ ...p, ...cfg, fraud_probas: null }))).catch(() => {});
    }
  }, [preloaded]);

  const set = useCallback((name: string, value: number | boolean | null) => {
    setSaved(false);
    setPreset(null);
    setParams((p) => ({ ...p, [name]: value }));
  }, []);

  const applyPreset = (key: string) => {
    const pr = PRESETS.find((x) => x.key === key);
    if (!pr) return;
    setPreset(key);
    setSaved(false);
    setParams({ ...pr.p, fraud_probas: null });
  };

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
    try {
      const { job_id } = await startSimulation(params);
      setSimJobId(job_id);
    } finally {
      setLoading(false);
    }
  }, [params, setSimJobId]);

  const onDone = useCallback((r: Record<string, unknown>) => setSimResult(r as unknown as SimulationResult), [setSimResult]);
  const onError = useCallback(() => setHasError(true), []);
  const onUpdate = useCallback((j: Job) => setJobActive(j.status === "running" || j.status === "pending"), []);

  const result = simResult;
  const autoVolume = params.volume_scale === null || params.volume_scale === undefined;
  const effVolume = autoVolume ? params.n_clients / 500000 : (params.volume_scale as number);
  const days = params.n_steps / 24;
  const cliPreset = PRESETS.find((x) => x.key === preset)?.cli;

  return (
    <Layout title="Simulation MoMTSim" subtitle="Journal brut rawLog_torch.parquet · sections 3.1 et 3.3 du mémoire">
      {fromHistory && (
        <div className="mb-4 flex items-center gap-2 px-4 py-2.5 rounded-xl bg-indigo-50 ring-1 ring-indigo-200 text-xs text-accent-blue">
          <RotateCcw className="w-3.5 h-3.5 flex-shrink-0" aria-hidden="true" />
          Paramètres rechargés depuis l'historique : modifiez le nombre de pas pour prolonger la simulation, puis relancez.
        </div>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-[380px_1fr] gap-6">
        {/* ── Réglages ─────────────────────────────────────────────── */}
        <div className="space-y-4">
          <div className="card">
            <h2 className="section-title mb-0.5">Régime</h2>
            <p className="text-xs text-text-muted mb-3">Préréglages de la section 3.1.2</p>
            <div className="grid grid-cols-2 gap-2">
              {PRESETS.map((pr) => (
                <button key={pr.key} onClick={() => applyPreset(pr.key)}
                  className={`text-left rounded-xl border px-3 py-2 transition-all duration-150 ${
                    preset === pr.key ? "border-indigo-300 bg-indigo-50 shadow-glow" : "border-border hover:border-border-hover hover:bg-bg-hover"}`}>
                  <p className={`text-xs font-semibold ${preset === pr.key ? "text-accent-blue" : "text-text-primary"}`}>{pr.label}</p>
                  <p className="text-2xs text-text-dim leading-snug mt-0.5">{pr.hint}</p>
                </button>
              ))}
            </div>
          </div>

          <div className="card space-y-4">
            <h2 className="section-title">Paramètres</h2>
            <div className="grid grid-cols-2 gap-3">
              <FormField label="Clients"   name="n_clients"   value={params.n_clients}   onChange={set} min={100} />
              <FormField label="Marchands" name="n_merchants" value={params.n_merchants} onChange={set} min={10} hint={`${(params.n_merchants / params.n_clients * 100).toFixed(2)} % des clients`} />
              <FormField label="Banques"   name="n_banks"     value={params.n_banks}     onChange={set} min={1} />
              <FormField label="Mules"     name="n_mules"     value={params.n_mules}     onChange={set} min={0} hint={`${(params.n_mules / params.n_clients * 100).toFixed(2)} % des clients`} />
              <FormField label="Pas (h)"   name="n_steps"     value={params.n_steps}     onChange={set} min={24} max={8760} hint={`${days.toFixed(days % 1 ? 1 : 0)} jours`} />
              <FormField label="Max slots" name="max_slots"   value={params.max_slots}   onChange={set} min={1} max={200} hint="tx / client / pas" />
              <FormField label="Graine"    name="seed"        value={params.seed}        onChange={set} min={0} />
              {!autoVolume && (
                <FormField label="Facteur de volume" name="volume_scale" value={params.volume_scale as number} onChange={set} min={0.0001} isFloat />
              )}
            </div>
            <Toggle label="Volume proportionné à la population" checked={autoVolume}
              onChange={(v) => set("volume_scale", v ? null : effVolume)}
              hint={`Facteur ${effVolume.toPrecision(3)} = n_clients / 500 000 (section 3.1.2). Désactiver pour un facteur libre.`} />
            <Toggle label="Injection proportionnelle au volume" checked={!!params.volume_follow}
              onChange={(v) => set("volume_follow", v)} hint="Doit être identique à la calibration." />
          </div>

          <div className="flex gap-2">
            <button className="btn-primary flex-1" onClick={launch} disabled={loading || jobActive} aria-busy={loading}>
              {loading
                ? <><Activity className="w-4 h-4 animate-spin-slow" aria-hidden="true" /> Lancement…</>
                : <><Play className="w-4 h-4" aria-hidden="true" /> Simuler</>}
            </button>
            <button className={`btn-secondary px-3 ${saved ? "text-accent-green border-emerald-300" : ""}`}
              onClick={handleSave} title="Sauvegarder dans sim_config.json" aria-label="Sauvegarder la configuration">
              {saved ? <CheckCircle2 className="w-4 h-4" aria-hidden="true" /> : <Save className="w-4 h-4" aria-hidden="true" />}
            </button>
          </div>
          <p className="caption">
            Le journal est écrit dans config/rawLog_torch.parquet (même fichier que le jeu d'entraînement). Les jeux du
            mémoire se génèrent plutôt en ligne de commande, qui archive l'ancien fichier :
          </p>
          <CommandBlock command={`python momtsim_cli.py generer --jeu ${cliPreset ?? "tous"}`} />

          <JobTracker jobId={simJobId} title="Simulation" onDone={onDone} onError={onError}
            onUpdate={onUpdate} onRestart={launch} />
        </div>

        {/* ── Résultats ────────────────────────────────────────────── */}
        <div className="space-y-5 min-w-0">
          {result ? (
            <div className="space-y-5 animate-fade-in">
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                <StatCard label="Transactions" value={result.n_transactions.toLocaleString("fr-FR")} icon={Activity} color="blue" />
                <StatCard label="Taux de fraude" value={(result.fraud_rate * 100).toFixed(2)} unit="%" icon={TrendingUp}
                  color={result.fraud_rate >= 0.2 && result.fraud_rate <= 0.26 ? "green" : "red"} description="cible 20 à 26 %" />
                <StatCard label="Pas simulés" value={result.steps_run} unit="h" icon={Clock} description={`${(result.steps_run / 24).toFixed(0)} jours`} />
                <StatCard label="Durée" value={formatDuration(result.elapsed_sim_s)} icon={Timer} />
              </div>

              {result.validation && <VerdictPanel verdict={result.validation} title="Contrôles du jeu simulé" commands={[]} />}

              {Object.keys(result.fraud_by_scenario).length > 0 && (
                <div className="card">
                  <h3 className="card-title mb-0.5">Répartition par scénario</h3>
                  <p className="text-xs text-text-muted mb-4">Part de chaque scénario dans la fraude ; cible 20 % chacun.</p>
                  <div className="space-y-3">
                    {Object.entries(result.fraud_by_scenario).map(([sc, v]) => (
                      <div key={sc} className="grid grid-cols-[96px_1fr_56px] items-center gap-3">
                        <span className="font-mono text-xs text-text-muted">{sc}</span>
                        <div className="relative">
                          <ProgressBar value={v * 100 / 0.4} size="sm" animated={false} tone={SCENARIO_COLORS[sc] ?? "brand"} />
                          <span className="absolute -top-1 h-3.5 w-px bg-slate-400 left-1/2" title="20 %" aria-hidden="true" />
                        </div>
                        <span className="font-mono text-xs text-text-primary text-right">{(v * 100).toFixed(1)} %</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {result.plain_summary && (
                <div className="card-sunken text-xs text-text-muted leading-relaxed">{result.plain_summary}</div>
              )}

              {CHARTS.filter((c) => result.charts[c.key]).map((c) => (
                <PlotlyEmbed key={c.key} html={result.charts[c.key]} title={c.title} height={c.height} />
              ))}
            </div>
          ) : (
            <EmptyState
              icon={Play}
              title="Aucune simulation"
              description="Choisissez un régime et lancez la simulation. Les probabilités calibrées sont chargées automatiquement."
            />
          )}
        </div>
      </div>
    </Layout>
  );
}
