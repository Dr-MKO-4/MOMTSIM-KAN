import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Target, Activity, TrendingDown, CheckCircle2, Save, RotateCcw, Cpu, Percent, Gauge,
} from "lucide-react";
import Layout from "../components/Layout";
import JobTracker from "../components/JobTracker";
import StatCard from "../components/StatCard";
import SseChart from "../components/SseChart";
import VerdictPanel from "../components/VerdictPanel";
import EmptyState from "../components/ui/EmptyState";
import FormField from "../components/ui/FormField";
import Toggle from "../components/ui/Toggle";
import CommandBlock from "../components/ui/CommandBlock";
import ProgressBar from "../components/ui/ProgressBar";
import {
  startCalibration, getCalibConfig, saveCalibConfig, getCalibrationReport,
} from "../api/client";
import { useAppState } from "../contexts/AppContext";
import type { CalibrationParams, CalibrationResult, CalibrationHistoryEntry, Job } from "../types/api";

/* Régime de calibration du mémoire (section 3.1.2) et paramètres SPSA (section 3.1.6) */
const MEMOIRE: CalibrationParams = {
  n_clients: 2000, n_merchants: 200, n_banks: 8, n_mules: 800, max_slots: 50,
  target_mid: 0.23, n_steps: 720, n_bins: 30, n_seeds_per_eval: 3,
  maxiter: 30, lr: 0.05, spsa_c: 0.02,
  volume_scale: 1.0, volume_follow: false, gain_schedule: "constant", n_workers: 0,
  resume: false, start_from_current: false,
};

const THETA = [
  { key: "ato",                label: "p ATO",          lo: 0.02,  hi: 0.5 },
  { key: "refund",             label: "p REFUND",       lo: 0.02,  hi: 0.5 },
  { key: "fake_credentials",   label: "p FAKE_CRED",    lo: 1e-4,  hi: 0.3 },
  { key: "split_deposit",      label: "p SPLIT_DEP",    lo: 0.02,  hi: 0.5 },
  { key: "smurfing_freq_mult", label: "α SMURFING",     lo: 0.5,   hi: 10 },
] as const;

const SCEN = ["ATO", "REFUND", "FAKE_CRED", "SPLIT_DEP", "SMURFING"];
const SCEN_COLOR = ["#E11D48", "#4F46E5", "#059669", "#7C3AED", "#D97706"];

const fmtSse = (v: number | null | undefined) =>
  v === null || v === undefined || !isFinite(v) ? "–" : v < 0.01 ? v.toExponential(3) : v.toFixed(4);

function ThetaTable({ result }: { result: CalibrationResult }) {
  return (
    <div className="card">
      <h3 className="card-title mb-0.5">Probabilités calibrées θ*</h3>
      <p className="text-xs text-text-muted mb-4">
        Position dans les bornes de Θ ; le repère gris indique le départ analytique θ0.
      </p>
      <div className="space-y-3.5">
        {THETA.map((t, i) => {
          const v = result.probas[t.key] ?? 0;
          const v0 = result.theta0?.[i];
          const pos = ((v - t.lo) / (t.hi - t.lo)) * 100;
          const pos0 = v0 !== undefined ? ((v0 - t.lo) / (t.hi - t.lo)) * 100 : null;
          return (
            <div key={t.key} className="grid grid-cols-[110px_1fr_auto] items-center gap-3">
              <span className="font-mono text-xs text-text-muted">{t.label}</span>
              <div className="relative h-2 rounded-full bg-bg-sunken">
                <div className="absolute inset-y-0 left-0 rounded-full bg-brand-gradient" style={{ width: `${Math.max(1.5, pos)}%` }} />
                {pos0 !== null && (
                  <span className="absolute -top-1 h-4 w-0.5 rounded bg-slate-400" style={{ left: `${pos0}%` }} title={`θ0 = ${v0?.toFixed(4)}`} />
                )}
              </div>
              <span className="font-mono text-xs text-right w-36">
                <span className="text-accent-blue font-semibold">{v.toFixed(4)}</span>
                {v0 !== undefined && <span className="text-text-dim"> · θ0 {v0.toFixed(4)}</span>}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ScenarioFit({ result }: { result: CalibrationResult }) {
  const be = result.best_eval;
  const Dr = result.Dr;
  if (!be || !Dr) return null;
  const totDs = be.Ds.map((r) => r.reduce((a, b) => a + b, 0));
  const totDr = Dr.map((r) => r.reduce((a, b) => a + b, 0));
  const sum = totDs.reduce((a, b) => a + b, 0) || 1;
  const fbin = be.Ds[0].map((_, t) => be.Ds.reduce((a, r) => a + r[t], 0));
  const daily = fbin.map((f, t) => (f + be.legit_bins[t] > 0 ? f / (f + be.legit_bins[t]) : 0));
  const maxDaily = Math.max(0.3, ...daily);
  const lo = 0.2, hi = 0.26;
  return (
    <div className="grid grid-cols-1 2xl:grid-cols-2 gap-5">
      <div className="card">
        <h3 className="card-title mb-0.5">Volume par scénario au meilleur point</h3>
        <p className="text-xs text-text-muted mb-4">Simulé D̄s (moyenne des réplications) contre cible Dr, sur l'horizon de calibration.</p>
        <div className="space-y-3">
          {SCEN.map((s, i) => {
            const ratio = totDr[i] > 0 ? totDs[i] / totDr[i] : 0;
            return (
              <div key={s}>
                <div className="flex justify-between text-xs mb-1">
                  <span className="font-mono font-medium" style={{ color: SCEN_COLOR[i] }}>{s}</span>
                  <span className="font-mono text-text-muted">
                    {(totDs[i] / sum * 100).toFixed(1)} % de la fraude · {(ratio * 100).toFixed(0)} % de la cible
                  </span>
                </div>
                <ProgressBar value={Math.min(100, ratio * 100)} size="sm" animated={false}
                  tone={ratio > 1.25 || ratio < 0.75 ? "amber" : "green"} />
              </div>
            );
          })}
        </div>
      </div>
      <div className="card">
        <h3 className="card-title mb-0.5">Taux de fraude par intervalle</h3>
        <p className="text-xs text-text-muted mb-4">
          Un intervalle = {result.config?.n_steps && result.config?.n_bins
            ? `${Number(result.config.n_steps) / Number(result.config.n_bins)} pas` : "1 jour"} ; bande verte : fourchette 20 à 26 %.
        </p>
        <div className="relative h-40 flex items-end gap-[3px]">
          <div className="absolute inset-x-0 bg-emerald-100/70 border-y border-emerald-300/60"
            style={{ bottom: `${(lo / maxDaily) * 100}%`, height: `${((hi - lo) / maxDaily) * 100}%` }} aria-hidden="true" />
          {daily.map((d, t) => (
            <div key={t} className="relative flex-1 rounded-t-sm transition-all duration-500"
              style={{ height: `${Math.max(1, (d / maxDaily) * 100)}%`,
                       background: d >= lo && d <= hi ? "#059669" : "#818CF8" }}
              title={`Intervalle ${t + 1} : ${(d * 100).toFixed(1)} %`} />
          ))}
        </div>
        <div className="flex justify-between text-2xs text-text-dim mt-1 font-mono">
          <span>1</span><span>{daily.length}</span>
        </div>
      </div>
    </div>
  );
}

export default function CalibrationPage() {
  const { calibJobId, calibResult, setCalibJobId, setCalibResult } = useAppState();

  const [params, setParams]     = useState<CalibrationParams>(MEMOIRE);
  const [loading, setLoading]   = useState(false);
  const [hasError, setHasError] = useState(false);
  const [saved, setSaved]       = useState(false);
  const [liveHistory, setLiveHistory] = useState<CalibrationHistoryEntry[]>([]);
  const [jobActive, setJobActive] = useState(false);

  const jobId  = calibJobId;
  const result = calibResult;

  useEffect(() => {
    getCalibConfig().then((cfg) => setParams((p) => ({ ...p, ...cfg }))).catch(() => {});
    // Dernier rapport, réévalué par le serveur avec les fichiers actuels
    getCalibrationReport().then((r) => setCalibResult(r)).catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const set = useCallback((name: string, value: number | boolean | string) => {
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
    setLiveHistory([]);
    try {
      const { job_id } = await startCalibration(params);
      setCalibJobId(job_id);
    } finally {
      setLoading(false);
    }
  }, [params, setCalibJobId]);

  const onDone = useCallback((r: Record<string, unknown>) => {
    setCalibResult(r as unknown as CalibrationResult);
  }, [setCalibResult]);
  const onError = useCallback(() => setHasError(true), []);
  const onUpdate = useCallback((j: Job) => {
    if (j.history) setLiveHistory(j.history);
    setJobActive(j.status === "running" || j.status === "pending");
  }, []);

  const running = jobActive && !hasError;
  const canLaunch = !loading && !jobActive;
  const nSims = 3 * params.n_seeds_per_eval * params.maxiter + params.n_seeds_per_eval;
  const cliCmd = useMemo(() => {
    const parts = ["python momtsim_cli.py calibrer"];
    if (params.gain_schedule === "spall") parts.push("--gains spall");
    if (params.volume_follow) parts.push("--volume-follow");
    if (params.start_from_current) parts.push("--depuis-theta-etoile");
    if (params.resume) parts.push("--reprendre");
    return parts.join(" ");
  }, [params]);

  const be = result?.best_eval;
  const sse0 = result?.sse_theta0;
  const gain0 = sse0 && result?.sse_final !== undefined ? (sse0 - result.sse_final) / sse0 : null;

  return (
    <Layout title="Calibration SSE/SPSA" subtitle="θ* = argmin Σc Σt (Dr − D̄s)² · section 3.1.6 du mémoire">
      <div className="grid grid-cols-1 xl:grid-cols-[380px_1fr] gap-6">
        {/* ── Réglages ─────────────────────────────────────────────── */}
        <div className="space-y-4">
          <div className="card space-y-5">
            <div className="flex items-start justify-between">
              <div>
                <h2 className="section-title">Régime de calibration</h2>
                <p className="text-xs text-text-muted">Section 3.1.2 du mémoire</p>
              </div>
              <button className="btn-sm btn-outline" onClick={() => { setParams(MEMOIRE); setSaved(false); }}
                title="Revenir aux valeurs du mémoire">
                <RotateCcw className="w-3 h-3" aria-hidden="true" /> Mémoire
              </button>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <FormField label="Clients"    name="n_clients"   value={params.n_clients}   onChange={set} min={50} />
              <FormField label="Marchands"  name="n_merchants" value={params.n_merchants} onChange={set} min={10} />
              <FormField label="Banques"    name="n_banks"     value={params.n_banks}     onChange={set} min={1} />
              <FormField label="Mules"      name="n_mules"     value={params.n_mules}     onChange={set} min={0} hint="Levier du taux de fraude" />
              <FormField label="Max slots"  name="max_slots"   value={params.max_slots}   onChange={set} min={1} />
              <FormField label="Pas"        name="n_steps"     value={params.n_steps}     onChange={set} min={24} />
              <FormField label="Intervalles T" name="n_bins"   value={params.n_bins}      onChange={set} min={5} />
              <FormField label="r cible"    name="target_mid"  value={params.target_mid}  onChange={set} min={0.1} max={0.5} isFloat />
            </div>

            <div className="h-px bg-border-subtle" />
            <div>
              <h2 className="section-title mb-3">SPSA</h2>
              <div className="grid grid-cols-2 gap-3">
                <FormField label="Itérations K_max" name="maxiter" value={params.maxiter} onChange={set} min={1} max={200} />
                <FormField label="Réplications K" name="n_seeds_per_eval" value={params.n_seeds_per_eval} onChange={set} min={1} />
                <FormField label="Pas a" name="lr" value={params.lr} onChange={set} min={0.0001} isFloat />
                <FormField label="Perturbation c" name="spsa_c" value={params.spsa_c} onChange={set} min={0.001} isFloat />
              </div>
              <div className="mt-3">
                <p className="label">Gains</p>
                <div className="segmented">
                  {(["constant", "spall"] as const).map((g) => (
                    <button key={g} className="segmented-item" data-active={params.gain_schedule === g}
                      onClick={() => set("gain_schedule", g)}>
                      {g === "constant" ? "Constants (mémoire)" : "Décroissants (Spall)"}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            <div className="h-px bg-border-subtle" />
            <div className="space-y-3">
              <h2 className="section-title">Exécution</h2>
              <FormField label="Processus en parallèle (0 = auto)" name="n_workers" value={params.n_workers} onChange={set} min={0} max={32} />
              <Toggle label="Injection proportionnelle au volume" checked={params.volume_follow}
                onChange={(v) => set("volume_follow", v)}
                hint="Choix méthodologique (voir le verdict) : à appliquer aussi à la génération." />
              <Toggle label="Partir de θ* actuel" checked={params.start_from_current}
                onChange={(v) => set("start_from_current", v)} hint="Au lieu du départ analytique θ0." />
              <Toggle label="Reprendre la calibration interrompue" checked={params.resume}
                onChange={(v) => set("resume", v)} hint="Point de reprise écrit après chaque itération." />
            </div>
          </div>

          <div className="card-sunken flex items-center justify-between text-xs">
            <span className="text-text-muted">Coût</span>
            <span className="font-mono text-text-primary">{nSims} simulations de {params.n_steps} pas</span>
          </div>

          <div className="flex gap-2">
            <button className="btn-primary flex-1" onClick={launch} disabled={!canLaunch} aria-busy={loading}>
              {loading
                ? <><Activity className="w-4 h-4 animate-spin-slow" aria-hidden="true" /> Lancement…</>
                : <><Target className="w-4 h-4" aria-hidden="true" /> Calibrer</>}
            </button>
            <button
              className={`btn-secondary px-3 ${saved ? "text-accent-green border-emerald-300" : ""}`}
              onClick={handleSave}
              title="Sauvegarder dans calib_config.json"
              aria-label="Sauvegarder la configuration"
            >
              {saved ? <CheckCircle2 className="w-4 h-4" aria-hidden="true" /> : <Save className="w-4 h-4" aria-hidden="true" />}
            </button>
          </div>

          <div className="space-y-1.5">
            <p className="metric-label">Sans l'interface (dossier MOMTSIM)</p>
            <CommandBlock command={cliCmd} />
            <CommandBlock command="python momtsim_cli.py verdict" comment="Relire le verdict" />
          </div>

          <JobTracker
            jobId={jobId}
            title="Calibration SPSA"
            onDone={onDone}
            onError={onError}
            onUpdate={onUpdate}
            onRestart={launch}
          />
        </div>

        {/* ── Résultats ────────────────────────────────────────────── */}
        <div className="space-y-5 min-w-0">
          {running && liveHistory.length > 0 && (
            <div className="card animate-fade-in">
              <h3 className="card-title mb-0.5">SSE en direct</h3>
              <p className="text-xs text-text-muted mb-3">{liveHistory.length} itération(s) évaluée(s)</p>
              <SseChart history={liveHistory} />
            </div>
          )}

          {result ? (
            <div className="space-y-5 animate-fade-in">
              {result.verdict && (
                <VerdictPanel verdict={result.verdict} title="Faut-il relancer la calibration ?" />
              )}

              <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                <StatCard label="SSE(θ*)" value={fmtSse(result.sse_final)} icon={TrendingDown} color="blue"
                  description={result.sse_zero_fraud ? `sans fraude : ${fmtSse(result.sse_zero_fraud)}` : undefined} />
                <StatCard label="Gain vs θ0" value={gain0 !== null ? (gain0 * 100).toFixed(1) : "–"} unit="%"
                  icon={Gauge} color={gain0 !== null && gain0 > 0.05 ? "green" : "amber"}
                  description={sse0 ? `SSE(θ0) = ${fmtSse(sse0)}` : undefined} />
                <StatCard label="Taux de fraude" value={be ? (be.fraud_rate * 100).toFixed(2) : "–"} unit="%"
                  icon={Percent} color={be && be.fraud_rate >= 0.2 && be.fraud_rate <= 0.26 ? "green" : "red"}
                  description="au meilleur point, cible 20 à 26 %" />
                <StatCard label="Itérations" value={result.history.length} icon={Cpu}
                  description={result.elapsed_s ? `${Math.round(result.elapsed_s / 60)} min, ${result.n_workers ?? 1} processus` : undefined} />
              </div>

              <div className="card">
                <h3 className="card-title mb-0.5">Trajectoire de l'objectif</h3>
                <p className="text-xs text-text-muted mb-3">
                  Une SSE proche de la ligne « sans fraude » signifie que la répartition temporelle de la cible n'est pas reproduite.
                </p>
                <SseChart history={result.history} sseZero={result.sse_zero_fraud} sseTheta0={result.sse_theta0} />
              </div>

              <ThetaTable result={result} />
              <ScenarioFit result={result} />
            </div>
          ) : (
            <EmptyState
              icon={Target}
              title="Aucune calibration disponible"
              description="Lancez la calibration ici ou en ligne de commande. θ* est sauvegardé dans calibrated_probas.json et utilisé automatiquement par la simulation et la génération des jeux."
            >
              <CommandBlock command="python momtsim_cli.py calibrer" />
            </EmptyState>
          )}
        </div>
      </div>
    </Layout>
  );
}
