import { useEffect, useState, useCallback } from "react";
import { Link } from "react-router-dom";
import {
  SlidersHorizontal, Target, Play, Layers, Network, ShieldAlert, TrendingUp, CreditCard,
  Split, Fish, Database, ArrowRight, CheckCircle2, AlertTriangle, CircleDashed, RefreshCcw,
} from "lucide-react";
import Layout from "../components/Layout";
import CommandBlock from "../components/ui/CommandBlock";
import { getHealth, getProbas, getCalibrationReport, getDatasets } from "../api/client";
import type { HealthStatus, CalibrationResult, DatasetEntry } from "../types/api";

const PIPELINE = [
  { step: 1, label: "Scénarios",    to: "/config",      icon: SlidersHorizontal, desc: "Paramètres des 5 scénarios", section: "§ 3.3" },
  { step: 2, label: "Calibration",  to: "/calibration", icon: Target,            desc: "θ* par SSE/SPSA", section: "§ 3.1.6" },
  { step: 3, label: "Simulation",   to: "/simulation",  icon: Play,              desc: "Journal brut des transactions", section: "§ 3.1" },
  { step: 4, label: "Features",     to: "/features",    icon: Layers,            desc: "12 caractéristiques", section: "§ 3.4" },
  { step: 5, label: "Validation",   to: "/kan",         icon: Network,           desc: "Décision topologique KAN", section: "§ 4" },
] as const;

const SCENARIOS = [
  { id: "ATO",       label: "Account Takeover", icon: ShieldAlert, cls: "text-accent-fraud bg-rose-50" },
  { id: "REFUND",    label: "Refund Fraud",     icon: TrendingUp,  cls: "text-accent-blue bg-indigo-50" },
  { id: "FAKE_CRED", label: "Fake Credentials", icon: CreditCard,  cls: "text-accent-green bg-emerald-50" },
  { id: "SPLIT_DEP", label: "Split Deposit",    icon: Split,       cls: "text-accent-purple bg-violet-50" },
  { id: "SMURFING",  label: "Smurfing",         icon: Fish,        cls: "text-accent-amber bg-amber-50" },
] as const;

const DS_LABEL: Record<string, string> = { entrainement: "Entraînement", validation: "Validation", test: "Test" };

function StateBadge({ state }: { state: "ok" | "warn" | "todo" | "redo" }) {
  const map = {
    ok:   { icon: CheckCircle2,  cls: "badge-green", label: "À jour" },
    warn: { icon: AlertTriangle, cls: "badge-amber", label: "Avec réserves" },
    redo: { icon: RefreshCcw,    cls: "badge-red",   label: "À refaire" },
    todo: { icon: CircleDashed,  cls: "badge-gray",  label: "À faire" },
  }[state];
  const I = map.icon;
  return <span className={map.cls}><I className="w-3 h-3" aria-hidden="true" />{map.label}</span>;
}

export default function DashboardPage() {
  const [health, setHealth]   = useState<HealthStatus | null>(null);
  const [probas, setProbas]   = useState<Record<string, number> | null>(null);
  const [calib, setCalib]     = useState<CalibrationResult | null>(null);
  const [datasets, setDatasets] = useState<DatasetEntry[] | null>(null);

  const load = useCallback(() => {
    getHealth().then(setHealth).catch(() => null);
    getProbas().then(setProbas).catch(() => setProbas(null));
    getCalibrationReport().then(setCalib).catch(() => setCalib(null));
    getDatasets().then(setDatasets).catch(() => setDatasets(null));
  }, []);

  useEffect(() => { load(); }, [load]);

  const cv = calib?.verdict?.verdict;
  const calibState: "ok" | "warn" | "todo" | "redo" =
    !calib ? (probas ? "redo" : "todo") : cv === "OK" ? "ok" : cv === "ACCEPTABLE" ? "warn" : "redo";

  const todo: string[] = [];
  if (calibState === "todo" || calibState === "redo") todo.push("python momtsim_cli.py calibrer");
  datasets?.forEach((d) => {
    if (!d.exists || d.stale || !d.report || d.report.verdict === "A REFAIRE")
      todo.push(`python momtsim_cli.py generer --jeu ${d.name}`);
  });

  return (
    <Layout title="Tableau de bord" subtitle="Simulation de fraude Mobile Money · zone CEMAC">
      {/* Bandeau */}
      <section className="relative overflow-hidden rounded-3xl bg-brand-gradient p-6 lg:p-8 text-white shadow-soft mb-6">
        <div className="absolute -right-16 -top-16 h-64 w-64 rounded-full bg-white/10 blur-2xl" aria-hidden="true" />
        <div className="relative grid gap-6 lg:grid-cols-[1fr_auto] items-center">
          <div>
            <p className="text-xs uppercase tracking-wider opacity-80">MoMTSim adapté · PyTorch</p>
            <h2 className="text-2xl font-semibold tracking-tight mt-1">Pipeline de génération des données</h2>
            <p className="text-sm opacity-85 mt-2 max-w-2xl leading-relaxed">
              Cinq scénarios de fraude injectés dans le modèle comportemental de MoMTSim, calibrés par SSE/SPSA
              pour une proportion de fraude de 20 à 26 %, puis trois jeux indépendants (entraînement, validation, test).
            </p>
          </div>
          <div className="flex gap-2">
            <Link to="/calibration" className="btn-md bg-white text-accent-blue hover:bg-indigo-50 rounded-xl">
              <Target className="w-4 h-4" aria-hidden="true" /> Calibration
            </Link>
            <Link to="/simulation" className="btn-md bg-white/15 text-white hover:bg-white/25 rounded-xl ring-1 ring-white/30">
              <Play className="w-4 h-4" aria-hidden="true" /> Simulation
            </Link>
          </div>
        </div>
      </section>

      {/* État */}
      <div className="grid grid-cols-1 xl:grid-cols-[1.2fr_1fr] gap-5 mb-6">
        <div className="card">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h2 className="section-title">État du pipeline</h2>
              <p className="text-xs text-text-muted">Calibration et jeux générés par momtsim_cli.py</p>
            </div>
            <button className="btn-sm btn-outline" onClick={load}><RefreshCcw className="w-3 h-3" aria-hidden="true" /> Actualiser</button>
          </div>
          <ul className="divide-y divide-border-subtle">
            <li className="flex items-center gap-3 py-3">
              <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-indigo-50 text-accent-blue"><Target className="w-4 h-4" aria-hidden="true" /></span>
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium">Calibration</p>
                <p className="text-xs text-text-muted truncate">
                  {calib ? (calib.verdict?.summary ?? "Rapport disponible")
                    : probas ? "calibrated_probas.json sans rapport (ancienne version)" : "Aucune calibration"}
                </p>
              </div>
              <StateBadge state={calibState} />
            </li>
            {(datasets ?? []).map((d) => {
              const st: "ok" | "warn" | "todo" | "redo" = !d.exists ? "todo"
                : d.stale || !d.report || d.report.verdict === "A REFAIRE" ? "redo"
                : d.report.verdict === "ACCEPTABLE" ? "warn" : "ok";
              return (
                <li key={d.name} className="flex items-center gap-3 py-3">
                  <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-slate-100 text-text-muted"><Database className="w-4 h-4" aria-hidden="true" /></span>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium">Jeu {DS_LABEL[d.name]}</p>
                    <p className="text-xs text-text-muted truncate">
                      {String(d.config.n_clients)} clients · {String(d.config.n_steps)} pas · graine {String(d.config.seed)}
                      {d.report ? ` · ${d.report.n_transactions.toLocaleString("fr-FR")} tx · fraude ${(d.report.fraud_rate * 100).toFixed(1)} %` : ""}
                      {d.stale ? " · θ* a changé depuis" : ""}
                      {d.exists && !d.report ? " · sans rapport (ancienne version)" : ""}
                    </p>
                  </div>
                  <StateBadge state={st} />
                </li>
              );
            })}
          </ul>
        </div>

        <div className="card space-y-3">
          <h2 className="section-title">À lancer</h2>
          <p className="text-xs text-text-muted">Dans un terminal, depuis le dossier MOMTSIM (environnement activé).</p>
          {todo.length === 0
            ? <p className="text-sm text-accent-green flex items-center gap-2"><CheckCircle2 className="w-4 h-4" /> Tout est à jour.</p>
            : todo.map((c) => <CommandBlock key={c} command={c} />)}
          <div className="pt-2 space-y-2">
            <CommandBlock command="python momtsim_cli.py etat" comment="Récapitulatif complet" />
            <CommandBlock command="python momtsim_cli.py test-rapide" comment="Vérifier le moteur (1 à 2 min)" />
          </div>
        </div>
      </div>

      {/* Étapes */}
      <section className="mb-6" aria-labelledby="pipeline-title">
        <h2 id="pipeline-title" className="section-title mb-3">Étapes</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-5 gap-3">
          {PIPELINE.map((p) => (
            <Link key={p.step} to={p.to} className="card-hover group" aria-label={`Étape ${p.step} : ${p.label}`}>
              <div className="flex items-center justify-between mb-3">
                <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-indigo-50 text-accent-blue group-hover:bg-brand-gradient group-hover:text-white transition-all">
                  <p.icon className="w-4 h-4" aria-hidden="true" />
                </span>
                <span className="text-2xs font-mono text-text-dim">{p.section}</span>
              </div>
              <p className="text-sm font-semibold">{p.step}. {p.label}</p>
              <p className="text-xs text-text-muted mt-0.5 flex items-center gap-1">
                {p.desc} <ArrowRight className="w-3 h-3 opacity-0 -translate-x-1 group-hover:opacity-100 group-hover:translate-x-0 transition-all" aria-hidden="true" />
              </p>
            </Link>
          ))}
        </div>
      </section>

      {/* Scénarios + fichiers */}
      <div className="grid grid-cols-1 xl:grid-cols-[1fr_340px] gap-5">
        <section aria-labelledby="scenarios-title">
          <h2 id="scenarios-title" className="section-title mb-3">Scénarios de fraude</h2>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3">
            {SCENARIOS.map((s) => (
              <div key={s.id} className="card-sm text-center">
                <span className={`mx-auto mb-2 flex h-10 w-10 items-center justify-center rounded-xl ${s.cls}`}>
                  <s.icon className="w-4 h-4" aria-hidden="true" />
                </span>
                <p className="font-mono font-semibold text-xs">{s.id}</p>
                <p className="text-2xs text-text-muted mt-0.5 leading-tight">{s.label}</p>
                {probas && (
                  <p className="text-2xs font-mono text-text-dim mt-1.5">
                    {s.id === "SMURFING" ? `α = ${probas.smurfing_freq_mult?.toFixed(2)}`
                      : `p = ${(probas[{ ATO: "ato", REFUND: "refund", FAKE_CRED: "fake_credentials", SPLIT_DEP: "split_deposit" }[s.id] as string] ?? 0).toFixed(3)}`}
                  </p>
                )}
              </div>
            ))}
          </div>
        </section>
        <div className="card">
          <h2 className="section-title mb-3">Fichiers</h2>
          {health ? (
            <ul className="space-y-2">
              {([
                ["fraudScenariosConfig", "fraudScenariosConfig.json"],
                ["calibrated_probas", "calibrated_probas.json"],
                ["rawLog_torch", "rawLog_torch.parquet"],
                ["featuresLog", "featuresLog.parquet"],
              ] as const).map(([k, name]) => (
                <li key={k} className="flex items-center gap-2 text-xs">
                  <span className={health.files[k] ? "status-dot-success" : "status-dot-muted"} />
                  <span className="font-mono text-text-muted flex-1 truncate">{name}</span>
                  <span className={health.files[k] ? "text-accent-green" : "text-text-dim"}>{health.files[k] ? "présent" : "absent"}</span>
                </li>
              ))}
            </ul>
          ) : (
            <div className="space-y-2">{[1, 2, 3, 4].map((i) => <div key={i} className="h-5 rounded bg-bg-sunken animate-pulse" />)}</div>
          )}
        </div>
      </div>
    </Layout>
  );
}
