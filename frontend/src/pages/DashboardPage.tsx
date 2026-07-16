import { useEffect, useState, useCallback } from "react";
import { Link } from "react-router-dom";
import {
  SlidersHorizontal,
  Play,
  Layers,
  Network,
  FileCheck,
  FileX,
  TrendingUp,
  ShieldAlert,
  Shuffle,
  CreditCard,
  Split,
  Fish,
} from "lucide-react";
import Layout from "../components/Layout";
import { getHealth, getProbas } from "../api/client";
import type { HealthStatus } from "../types/api";

/* ── Pipeline steps ─────────────────────────────────────────────────────── */
const PIPELINE = [
  {
    step: "1", label: "Configuration",    to: "/config",
    icon: SlidersHorizontal, desc: "Paramétrage des 5 scénarios de fraude",
    section: "§ 3.1",
  },
  {
    step: "2", label: "Simulation",       to: "/simulation",
    icon: Play,              desc: "Génération du rawLog (720 steps × N clients)",
    section: "§ 3.2",
  },
  {
    step: "3", label: "Features",         to: "/features",
    icon: Layers,            desc: "12 features vectorisées (éqs. 3.8–3.19)",
    section: "§ 3.2.6",
  },
  {
    step: "4", label: "Validation KAN",   to: "/kan",
    icon: Network,           desc: "Quick Decision Rule (VE₂, J_Fisher, D_KS)",
    section: "§ 4.1",
  },
] as const;

/* ── Fraud scenarios ────────────────────────────────────────────────────── */
const SCENARIOS = [
  { id: "ATO",       label: "Account Takeover",  icon: ShieldAlert, colorClass: "text-accent-fraud",  bgClass: "bg-accent-fraud/10",  section: "3.2.1" },
  { id: "REFUND",    label: "Refund Fraud",       icon: TrendingUp,  colorClass: "text-accent-blue",   bgClass: "bg-accent-blue/10",   section: "3.2.2" },
  { id: "FAKE_CRED", label: "Fake Credentials",  icon: CreditCard,  colorClass: "text-accent-green",  bgClass: "bg-accent-green/10",  section: "3.2.3" },
  { id: "SPLIT_DEP", label: "Split Deposit",      icon: Split,       colorClass: "text-accent-purple", bgClass: "bg-accent-purple/10", section: "3.2.4" },
  { id: "SMURFING",  label: "Smurfing",           icon: Fish,        colorClass: "text-accent-amber",  bgClass: "bg-accent-amber/10",  section: "3.2.5" },
] as const;

/* ── File status row ────────────────────────────────────────────────────── */
function FileStatusRow({ ok, name }: { ok: boolean; name: string }) {
  return (
    <div className="flex items-center gap-3 py-2.5 border-b border-border/50 last:border-0">
      {ok
        ? <FileCheck className="w-4 h-4 text-accent-green flex-shrink-0" aria-hidden="true" />
        : <FileX    className="w-4 h-4 text-text-dim flex-shrink-0"     aria-hidden="true" />
      }
      <span className="text-xs font-mono text-text-muted flex-1 truncate">{name}</span>
      <span className={`text-2xs font-mono ${ok ? "text-accent-green" : "text-text-dim"}`}>
        {ok ? "présent" : "manquant"}
      </span>
    </div>
  );
}

/* ── Page ───────────────────────────────────────────────────────────────── */
export default function DashboardPage() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [probas, setProbas] = useState<Record<string, number> | null>(null);

  const load = useCallback(() => {
    getHealth().then(setHealth).catch(() => null);
    getProbas().then(setProbas).catch(() => null);
  }, []);

  useEffect(() => { load(); }, [load]);

  return (
    <Layout
      title="MoMTSim-KAN Dashboard"
      subtitle="Pipeline de simulation de fraude Mobile Money — CEMAC/Cameroun"
    >
      {/* ── Pipeline ───────────────────────────────────────────────────── */}
      <section className="mb-6" aria-labelledby="pipeline-title">
        <div className="mb-3">
          <h2 id="pipeline-title" className="section-title">Pipeline d'exécution</h2>
          <p className="text-xs text-text-muted mt-0.5">Suivez les étapes dans l'ordre</p>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
          {PIPELINE.map((p) => (
            <Link
              key={p.step}
              to={p.to}
              className="card-hover group"
              aria-label={`Aller à l'étape ${p.step} : ${p.label}`}
            >
              <div className="flex items-start gap-3">
                <div className="w-7 h-7 rounded-lg bg-accent-blue/10 border border-accent-blue/20 flex items-center justify-center flex-shrink-0 mt-0.5 group-hover:bg-accent-blue/20 transition-colors duration-150">
                  <span className="text-accent-blue text-xs font-mono font-bold">{p.step}</span>
                </div>
                <div className="min-w-0">
                  <div className="flex items-center gap-2 mb-1">
                    <p.icon className="w-3.5 h-3.5 text-text-dim group-hover:text-accent-blue transition-colors duration-150 flex-shrink-0" aria-hidden="true" />
                    <p className="text-sm font-medium text-text-primary leading-none">{p.label}</p>
                  </div>
                  <p className="text-xs text-text-muted leading-relaxed">{p.desc}</p>
                  <p className="text-2xs text-text-dim font-mono mt-1.5">{p.section}</p>
                </div>
              </div>
            </Link>
          ))}
        </div>
      </section>

      {/* ── État des fichiers + Probabilités calibrées ──────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4 mb-6">
        {/* File status */}
        <div className="card" aria-labelledby="files-title">
          <h2 id="files-title" className="section-title mb-3">État des fichiers</h2>
          {health ? (
            <div>
              <FileStatusRow ok={health.files.fraudScenariosConfig} name="fraudScenariosConfig.json" />
              <FileStatusRow ok={health.files.rawLog_torch}         name="rawLog_torch.csv" />
              <FileStatusRow ok={health.files.featuresLog}          name="featuresLog.csv" />
              <FileStatusRow ok={health.files.calibrated_probas}    name="calibrated_probas.json" />
            </div>
          ) : (
            <div className="space-y-2.5">
              {[1, 2, 3, 4].map((i) => (
                <div key={i} className="h-8 bg-bg-secondary rounded animate-pulse" />
              ))}
            </div>
          )}
        </div>

        {/* Calibrated probas */}
        <div className="card" aria-labelledby="probas-title">
          <h2 id="probas-title" className="section-title mb-3">Probabilités calibrées</h2>
          {probas ? (
            <div className="space-y-2.5">
              {Object.entries(probas).map(([k, v]) => (
                <div key={k} className="flex items-center gap-3">
                  <span className="text-xs font-mono text-text-muted w-36 flex-shrink-0 truncate">{k}</span>
                  <div className="flex-1 bg-bg-secondary rounded-full h-1" role="presentation">
                    <div
                      className="bg-accent-blue h-1 rounded-full transition-all duration-500"
                      style={{ width: `${Math.min(typeof v === "number" ? v * 100 * 5 : 0, 100)}%` }}
                    />
                  </div>
                  <span className="badge-blue flex-shrink-0 font-mono">
                    {typeof v === "number" ? v.toFixed(4) : v}
                  </span>
                </div>
              ))}
            </div>
          ) : (
            <div className="flex flex-col gap-2">
              <p className="text-sm text-text-muted">Aucune calibration disponible.</p>
              <Link to="/calibration" className="text-xs text-accent-blue hover:text-blue-400 transition-colors duration-150">
                Lancer la calibration →
              </Link>
            </div>
          )}
        </div>
      </div>

      {/* ── Scénarios de fraude ─────────────────────────────────────── */}
      <section aria-labelledby="scenarios-title">
        <div className="mb-3">
          <h2 id="scenarios-title" className="section-title">Scénarios de fraude</h2>
          <p className="text-xs text-text-muted mt-0.5">Section 3.2 du mémoire</p>
        </div>
        <div className="grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-5 gap-3">
          {SCENARIOS.map((s) => (
            <div key={s.id} className="card-sm text-center">
              <div className={`w-8 h-8 rounded-lg ${s.bgClass} flex items-center justify-center mx-auto mb-2`}>
                <s.icon className={`w-4 h-4 ${s.colorClass}`} aria-hidden="true" />
              </div>
              <p className={`font-mono font-bold text-sm ${s.colorClass}`}>{s.id}</p>
              <p className="text-xs text-text-muted mt-0.5 leading-tight">{s.label}</p>
              <p className="text-2xs text-text-dim font-mono mt-1.5">§ {s.section}</p>
            </div>
          ))}
        </div>
      </section>
    </Layout>
  );
}
