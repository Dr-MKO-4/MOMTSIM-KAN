import { useCallback, useEffect, useState } from "react";
import { Database, Filter, RefreshCw, ShieldAlert, Table2 } from "lucide-react";
import Layout from "../components/Layout";
import DataTable from "../components/DataTable";
import EmptyState from "../components/ui/EmptyState";
import StatCard from "../components/StatCard";
import { fetchFeaturesDataPage, fetchRawDataPage } from "../api/client";
import type { DataPage } from "../types/api";

type Tab = "features" | "raw";

const TABS: { id: Tab; label: string; desc: string }[] = [
  { id: "features", label: "Dataset final (features)", desc: "featuresLog.parquet  12 features KAN" },
  { id: "raw",      label: "Raw Log",                  desc: "rawLog_torch.parquet  transactions brutes" },
];

export default function DatasetPage() {
  const [tab, setTab]               = useState<Tab>("features");
  const [filterFraud, setFilterFraud] = useState(false);
  const [page, setPage]             = useState(1);
  const [data, setData]             = useState<DataPage | null>(null);
  const [loading, setLoading]       = useState(false);
  const [error, setError]           = useState<string | null>(null);

  const load = useCallback(async (t: Tab, p: number, ff: boolean) => {
    setLoading(true);
    setError(null);
    try {
      const result = t === "features"
        ? await fetchFeaturesDataPage(p, 100, ff)
        : await fetchRawDataPage(p, 100, ff);
      setData(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Erreur de chargement.");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setPage(1);
    setData(null);
    load(tab, 1, filterFraud);
  }, [tab, filterFraud, load]);

  const handlePageChange = useCallback((p: number) => {
    setPage(p);
    load(tab, p, filterFraud);
  }, [tab, filterFraud, load]);

  const fraudCount = data
    ? filterFraud ? data.total : undefined
    : undefined;

  return (
    <Layout
      title="Visualisation du dataset"
      subtitle="Exploration paginée des données simulées  rawLog et featuresLog"
    >
      {/* Onglets */}
      <div className="flex gap-1 mb-5 p-1 bg-bg-secondary border border-border w-fit">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={[
              "px-4 py-2 text-sm font-medium transition-all duration-150",
              tab === t.id
                ? "bg-accent-blue text-white shadow-sm"
                : "text-text-muted hover:text-text-primary hover:bg-bg-hover",
            ].join(" ")}
            aria-pressed={tab === t.id}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Sous-titre onglet actif */}
      <p className="text-xs text-text-muted font-mono mb-4">
        {TABS.find((t) => t.id === tab)?.desc}
      </p>

      {/* Toolbar */}
      <div className="flex items-center gap-3 mb-4 flex-wrap">
        <div className="flex items-center gap-2">
          <Filter className="w-3.5 h-3.5 text-text-dim" aria-hidden="true" />
          <span className="text-xs text-text-muted">Filtre :</span>
          <button
            className={[
              "btn-sm transition-all duration-150",
              !filterFraud ? "bg-accent-blue text-white" : "btn-secondary text-text-muted",
            ].join(" ")}
            onClick={() => setFilterFraud(false)}
          >
            Toutes les tx
          </button>
          <button
            className={[
              "btn-sm flex items-center gap-1.5 transition-all duration-150",
              filterFraud ? "bg-accent-fraud text-white" : "btn-secondary text-text-muted",
            ].join(" ")}
            onClick={() => setFilterFraud(true)}
          >
            <ShieldAlert className="w-3 h-3" aria-hidden="true" />
            Fraudes seulement
          </button>
        </div>

        <button
          className="btn-ghost ml-auto flex items-center gap-1.5"
          onClick={() => load(tab, page, filterFraud)}
          disabled={loading}
          aria-label="Actualiser"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin-slow" : ""}`} aria-hidden="true" />
          Actualiser
        </button>
      </div>

      {/* Stats rapides */}
      {data && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-5">
          <StatCard
            label="Lignes totales"
            value={data.total.toLocaleString("fr-FR")}
            icon={Database}
            color="blue"
          />
          <StatCard
            label="Colonnes"
            value={data.columns.length}
            icon={Table2}
            color="green"
          />
          <StatCard
            label="Pages"
            value={data.total_pages.toLocaleString("fr-FR")}
            icon={RefreshCw}
            color="default"
          />
          {fraudCount !== undefined && (
            <StatCard
              label="Transactions fraude"
              value={fraudCount.toLocaleString("fr-FR")}
              icon={ShieldAlert}
              color="red"
            />
          )}
        </div>
      )}

      {/* Contenu principal */}
      {error ? (
        <div className="card border-accent-fraud/30 bg-accent-fraud/5">
          <p className="text-xs text-accent-fraud font-mono">{error}</p>
          <p className="text-xs text-text-muted mt-1">
            {tab === "features"
              ? "Lancez d'abord le Feature Engineering pour générer featuresLog.parquet."
              : "Lancez d'abord une simulation pour générer rawLog_torch.parquet."}
          </p>
        </div>
      ) : !data && !loading ? (
        <EmptyState
          icon={Database}
          title="Aucune donnée chargée"
          description={
            tab === "features"
              ? "Lancez le Feature Engineering pour générer le dataset final."
              : "Lancez une simulation pour générer le rawLog."
          }
        />
      ) : loading && !data ? (
        <div className="flex justify-center py-16">
          <RefreshCw className="w-5 h-5 text-text-dim animate-spin-slow" aria-hidden="true" />
        </div>
      ) : data ? (
        <div className={loading ? "opacity-60 pointer-events-none transition-opacity duration-200" : ""}>
          <DataTable
            data={data}
            onPageChange={handlePageChange}
            loading={loading}
          />
        </div>
      ) : null}
    </Layout>
  );
}
