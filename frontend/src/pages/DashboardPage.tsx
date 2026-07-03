import { useEffect, useState } from "react";
import Layout from "../components/Layout";
import StatCard from "../components/StatCard";
import { getHealth, getProbas } from "../api/client";
import type { HealthStatus } from "../types/api";

function FileStatus({ ok, name }: { ok: boolean; name: string }) {
  return (
    <div className="flex items-center gap-3 py-2">
      <span
        className={`w-2.5 h-2.5 rounded-full flex-shrink-0 ${ok ? "bg-accent-green" : "bg-bg-secondary border border-border"}`}
      />
      <span className="text-sm font-mono text-text-muted">{name}</span>
      <span className={`ml-auto text-xs ${ok ? "text-accent-green" : "text-text-dim"}`}>
        {ok ? "présent" : "manquant"}
      </span>
    </div>
  );
}

export default function DashboardPage() {
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [probas, setProbas] = useState<Record<string, number> | null>(null);

  useEffect(() => {
    getHealth().then(setHealth).catch(() => null);
    getProbas().then(setProbas).catch(() => null);
  }, []);

  const pipeline = [
    { step: "1", label: "Configuration", desc: "Paramétrage des 5 scénarios de fraude", to: "/config" },
    { step: "2", label: "Simulation", desc: "Génération du rawLog (720 steps × N_clients)", to: "/simulation" },
    { step: "3", label: "Features", desc: "Calcul des 12 features vectorisées (éqs. 3.8–3.19)", to: "/features" },
    { step: "4", label: "Validation KAN", desc: "Quick Decision Rule (VE₂, J_Fisher, D_KS)", to: "/kan" },
  ];

  return (
    <Layout
      title="MoMTSim-KAN Dashboard"
      subtitle="Pipeline de simulation de fraude Mobile Money — CEMAC/Cameroun"
    >
      {/* Pipeline steps */}
      <section className="mb-8">
        <h2 className="section-title">Pipeline</h2>
        <p className="section-subtitle">Exécutez les étapes dans l'ordre</p>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {pipeline.map((p) => (
            <a key={p.step} href={p.to} className="card hover:border-accent-blue/50 transition-colors cursor-pointer">
              <div className="flex items-start gap-3">
                <span className="w-7 h-7 rounded-full bg-accent-blue/15 text-accent-blue text-xs font-mono font-bold flex items-center justify-center flex-shrink-0 mt-0.5">
                  {p.step}
                </span>
                <div>
                  <p className="text-sm font-medium text-text-primary">{p.label}</p>
                  <p className="text-xs text-text-muted mt-0.5 leading-relaxed">{p.desc}</p>
                </div>
              </div>
            </a>
          ))}
        </div>
      </section>

      {/* État des fichiers */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-8">
        <div className="card">
          <h2 className="section-title mb-3">État des fichiers</h2>
          {health ? (
            <div className="divide-y divide-border">
              <FileStatus ok={health.files.fraudScenariosConfig} name="fraudScenariosConfig.json" />
              <FileStatus ok={health.files.rawLog_torch} name="rawLog_torch.csv" />
              <FileStatus ok={health.files.featuresLog} name="featuresLog.csv" />
              <FileStatus ok={health.files.calibrated_probas} name="calibrated_probas.json" />
            </div>
          ) : (
            <p className="text-sm text-text-dim">Chargement…</p>
          )}
        </div>

        <div className="card">
          <h2 className="section-title mb-3">Probabilités calibrées</h2>
          {probas ? (
            <div className="space-y-2">
              {Object.entries(probas).map(([k, v]) => (
                <div key={k} className="flex items-center justify-between">
                  <span className="text-sm font-mono text-text-muted">{k}</span>
                  <span className="badge-blue font-mono">{typeof v === "number" ? v.toFixed(4) : v}</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-text-dim">
              Aucune calibration disponible.{" "}
              <a href="/calibration" className="text-accent-blue hover:underline">Lancer la calibration →</a>
            </p>
          )}
        </div>
      </div>

      {/* Scénarios */}
      <section>
        <h2 className="section-title mb-3">Scénarios de fraude (section 3.2)</h2>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
          {[
            { id: "ATO", label: "Account Takeover", color: "text-accent-fraud", section: "3.2.1" },
            { id: "REFUND", label: "Refund Fraud", color: "text-accent-blue", section: "3.2.2" },
            { id: "FAKE_CRED", label: "Fake Credentials", color: "text-accent-green", section: "3.2.3" },
            { id: "SPLIT_DEP", label: "Split Deposit", color: "text-accent-purple", section: "3.2.4" },
            { id: "SMURFING", label: "Smurfing", color: "text-accent-amber", section: "3.2.5" },
          ].map((s) => (
            <div key={s.id} className="card text-center">
              <p className={`font-mono font-bold text-base ${s.color}`}>{s.id}</p>
              <p className="text-xs text-text-muted mt-1">{s.label}</p>
              <p className="text-2xs text-text-dim mt-1 font-mono">§ {s.section}</p>
            </div>
          ))}
        </div>
      </section>
    </Layout>
  );
}
