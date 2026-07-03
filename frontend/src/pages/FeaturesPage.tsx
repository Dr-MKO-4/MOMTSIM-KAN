import { useState } from "react";
import Layout from "../components/Layout";
import JobTracker from "../components/JobTracker";
import PlotlyEmbed from "../components/PlotlyEmbed";
import StatCard from "../components/StatCard";
import { startFeatures } from "../api/client";
import type { FeatureResult } from "../types/api";

const FEATURE_META: Record<string, { eq: string; desc: string }> = {
  r1:                   { eq: "3.10", desc: "Ratio montant / solde initial" },
  r2:                   { eq: "3.11", desc: "Ratio montant / solde final" },
  delta_B_orig:         { eq: "3.8",  desc: "Variation du solde émetteur" },
  delta_B_dest:         { eq: "3.9",  desc: "Variation du solde destinataire" },
  delta_commission_ratio: { eq: "3.13", desc: "Commission mule (smurfing)" },
  var_agent_split:      { eq: "3.14", desc: "Variance intra-agent (split deposit)" },
  rho_rupture:          { eq: "3.15", desc: "Rupture de comportement (fake credentials)" },
  rho_refund:           { eq: "3.16", desc: "Ratio remboursements/paiements" },
  v1h:                  { eq: "3.17", desc: "Vélocité sur 1h" },
  flag_nuit:            { eq: "3.18", desc: "Transaction nocturne (22h–6h)" },
  rho_nouveau:          { eq: "3.19", desc: "Ratio destinataires inconnus (30j)" },
  flag_anomalie:        { eq: "3.12", desc: "Anomalie fenêtre 10 tx glissant" },
};

export default function FeaturesPage() {
  const [jobId, setJobId] = useState<string | null>(null);
  const [result, setResult] = useState<FeatureResult | null>(null);
  const [loading, setLoading] = useState(false);

  const launch = async () => {
    setLoading(true);
    setResult(null);
    try {
      const { job_id } = await startFeatures();
      setJobId(job_id);
    } finally {
      setLoading(false);
    }
  };

  const onDone = (r: Record<string, unknown>) => {
    setResult(r as unknown as FeatureResult);
  };

  return (
    <Layout
      title="Feature Engineering"
      subtitle="12 features vectorisées — section 3.2.6 / éqs. 3.8–3.19"
    >
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        {/* Panneau gauche */}
        <div className="xl:col-span-1 space-y-4">
          <div className="card">
            <h2 className="section-title">Catalogue des features</h2>
            <p className="section-subtitle">Formalisées en section 3.2.6</p>
            <div className="space-y-1.5 mt-2">
              {Object.entries(FEATURE_META).map(([feat, meta]) => (
                <div key={feat} className="flex items-start gap-2 py-1.5 border-b border-border/50 last:border-0">
                  <span className="badge-blue flex-shrink-0 mt-0.5">§{meta.eq}</span>
                  <div>
                    <p className="text-xs font-mono text-text-primary">{feat}</p>
                    <p className="text-2xs text-text-dim mt-0.5">{meta.desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <button
            className="btn-primary w-full text-sm"
            onClick={launch}
            disabled={loading || (jobId !== null && result === null)}
          >
            {loading ? "Lancement…" : "∑ Calculer les features"}
          </button>

          <p className="text-xs text-text-dim text-center">
            Requiert rawLog_torch.csv (simulation préalable)
          </p>

          <JobTracker jobId={jobId} onDone={onDone} onError={() => {}} />
        </div>

        {/* Résultats */}
        <div className="xl:col-span-2 space-y-6">
          {result ? (
            <>
              <div className="grid grid-cols-3 gap-4">
                <StatCard label="Transactions" value={result.n_rows.toLocaleString("fr-FR")} color="blue" />
                <StatCard label="Features calculées" value={result.n_features} color="green" />
                <StatCard label="Fichier généré" value="featuresLog.csv" />
              </div>

              {result.charts.r1_r2_scatter && (
                <PlotlyEmbed html={result.charts.r1_r2_scatter} title="r1 vs r2 — signature ATO" height={460} />
              )}
              {result.charts.distributions && (
                <PlotlyEmbed html={result.charts.distributions} title="Distributions des features clés" height={560} />
              )}
              {result.charts.smurfing_delta && (
                <PlotlyEmbed html={result.charts.smurfing_delta} title="Commission mule — Smurfing (Zhdanova et al.)" height={380} />
              )}
            </>
          ) : (
            <div className="card flex flex-col items-center justify-center min-h-[300px] text-center">
              <p className="text-4xl mb-4 text-text-dim font-mono">Σ</p>
              <p className="text-sm text-text-muted">
                Lancez le calcul des features sur le rawLog simulé.
              </p>
              <p className="text-xs text-text-dim mt-1">
                Le calcul est vectorisé (pandas + numpy, O(n log n)).
              </p>
            </div>
          )}
        </div>
      </div>
    </Layout>
  );
}
