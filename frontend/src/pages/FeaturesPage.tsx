import { useCallback, useState } from "react";
import { Layers, Hash, Activity, FileText } from "lucide-react";
import Layout from "../components/Layout";
import JobTracker from "../components/JobTracker";
import PlotlyEmbed from "../components/PlotlyEmbed";
import StatCard from "../components/StatCard";
import EmptyState from "../components/ui/EmptyState";
import { startFeatures } from "../api/client";
import type { FeatureResult } from "../types/api";

const FEATURE_META: Record<string, { eq: string; desc: string }> = {
  r1:                     { eq: "3.10", desc: "Ratio montant / solde initial" },
  r2:                     { eq: "3.11", desc: "Ratio montant / solde final" },
  delta_B_orig:           { eq: "3.8",  desc: "Variation du solde émetteur" },
  delta_B_dest:           { eq: "3.9",  desc: "Variation du solde destinataire" },
  delta_commission_ratio: { eq: "3.13", desc: "Commission mule — Smurfing" },
  var_agent_split:        { eq: "3.14", desc: "Variance intra-agent — Split Deposit" },
  rho_rupture:            { eq: "3.15", desc: "Rupture de comportement — Fake Cred" },
  rho_refund:             { eq: "3.16", desc: "Ratio remboursements / paiements" },
  v1h:                    { eq: "3.17", desc: "Vélocité sur 1h" },
  flag_nuit:              { eq: "3.18", desc: "Transaction nocturne (22h–6h)" },
  rho_nouveau:            { eq: "3.19", desc: "Ratio destinataires inconnus (30j)" },
  flag_anomalie:          { eq: "3.12", desc: "Anomalie sur fenêtre 10 tx" },
};

export default function FeaturesPage() {
  const [jobId, setJobId]     = useState<string | null>(null);
  const [result, setResult]   = useState<FeatureResult | null>(null);
  const [loading, setLoading] = useState(false);

  const launch = useCallback(async () => {
    setLoading(true);
    setResult(null);
    try {
      const { job_id } = await startFeatures();
      setJobId(job_id);
    } finally {
      setLoading(false);
    }
  }, []);

  const onDone = useCallback((r: Record<string, unknown>) => {
    setResult(r as unknown as FeatureResult);
  }, []);

  const canLaunch = !loading && !(jobId !== null && result === null);

  return (
    <Layout
      title="Feature Engineering"
      subtitle="12 features vectorisées — section 3.2.6 / éqs. 3.8–3.19"
    >
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-5">
        {/* ── Left panel ────────────────────────────────────────────── */}
        <div className="xl:col-span-1 space-y-4">
          <div className="card">
            <h2 className="section-title mb-0.5">Catalogue des features</h2>
            <p className="text-xs text-text-muted mb-3">Formalisées en section 3.2.6</p>
            <div className="space-y-0.5">
              {Object.entries(FEATURE_META).map(([feat, meta]) => (
                <div
                  key={feat}
                  className="flex items-start gap-2.5 py-2 border-b border-border/40 last:border-0"
                >
                  <span className="badge-blue flex-shrink-0 mt-0.5">§{meta.eq}</span>
                  <div className="min-w-0">
                    <p className="text-xs font-mono text-text-primary leading-none">{feat}</p>
                    <p className="text-2xs text-text-dim mt-0.5">{meta.desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <button
            className="btn-primary w-full"
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
                <Layers className="w-4 h-4" aria-hidden="true" />
                Calculer les features
              </>
            )}
          </button>

          <p className="caption text-center">
            Requiert rawLog_torch.csv (simulation préalable)
          </p>

          <JobTracker jobId={jobId} onDone={onDone} onError={() => {}} />
        </div>

        {/* ── Results panel ─────────────────────────────────────────── */}
        <div className="xl:col-span-2 space-y-5">
          {result ? (
            <div className="space-y-5 animate-fade-in">
              <div className="grid grid-cols-3 gap-3">
                <StatCard
                  label="Transactions"
                  value={result.n_rows.toLocaleString("fr-FR")}
                  icon={Activity}
                  color="blue"
                />
                <StatCard
                  label="Features calculées"
                  value={result.n_features}
                  icon={Hash}
                  color="green"
                />
                <StatCard
                  label="Fichier produit"
                  value="featuresLog"
                  unit=".csv"
                  icon={FileText}
                />
              </div>

              {result.charts.r1_r2_scatter && (
                <PlotlyEmbed
                  html={result.charts.r1_r2_scatter}
                  title="r₁ vs r₂ — signature ATO (éqs. 3.10–3.11)"
                  height={460}
                />
              )}
              {result.charts.distributions && (
                <PlotlyEmbed
                  html={result.charts.distributions}
                  title="Distributions des features clés — légitime vs fraude"
                  height={540}
                />
              )}
              {result.charts.smurfing_delta && (
                <PlotlyEmbed
                  html={result.charts.smurfing_delta}
                  title="Commission mule observée — Smurfing (Zhdanova et al., éq. 3.13)"
                  height={380}
                />
              )}
            </div>
          ) : (
            <EmptyState
              icon={Layers}
              title="Aucun résultat disponible"
              description="Lancez le calcul des features sur le rawLog simulé. Le traitement est vectorisé (pandas + numpy, O(n log n))."
            />
          )}
        </div>
      </div>
    </Layout>
  );
}
