import { useEffect, useState } from "react";
import Layout from "../components/Layout";
import { getConfig, updateConfig, listBackups, restoreBackup } from "../api/client";
import type { FraudConfig, BackupEntry } from "../types/api";

function NumField({
  label, path, value, onChange, min, max, step = 1, isFloat = false,
}: {
  label: string; path: string; value: number;
  onChange: (path: string, v: number) => void;
  min?: number; max?: number; step?: number; isFloat?: boolean;
}) {
  return (
    <div>
      <label className="label">{label}</label>
      <input
        type="number"
        className="input"
        value={value}
        min={min}
        max={max}
        step={isFloat ? 0.01 : step}
        onChange={(e) => onChange(path, parseFloat(e.target.value))}
      />
    </div>
  );
}

function setNested(obj: Record<string, unknown>, path: string, val: unknown): Record<string, unknown> {
  const keys = path.split(".");
  const result = { ...obj };
  let cursor: Record<string, unknown> = result;
  for (let i = 0; i < keys.length - 1; i++) {
    cursor[keys[i]] = { ...(cursor[keys[i]] as Record<string, unknown>) };
    cursor = cursor[keys[i]] as Record<string, unknown>;
  }
  cursor[keys[keys.length - 1]] = val;
  return result;
}

export default function ConfigPage() {
  const [config, setConfig] = useState<FraudConfig | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [backups, setBackups] = useState<BackupEntry[]>([]);
  const [activeTab, setActiveTab] = useState<keyof FraudConfig>("global");

  useEffect(() => {
    getConfig().then(setConfig).catch((e) => setError(String(e)));
    listBackups().then(setBackups).catch(() => null);
  }, []);

  const set = (path: string, val: number) => {
    if (!config) return;
    setConfig(setNested(config as unknown as Record<string, unknown>, path, val) as unknown as FraudConfig);
  };

  const save = async () => {
    if (!config) return;
    setSaving(true);
    setError(null);
    try {
      await updateConfig(config);
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
      listBackups().then(setBackups);
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  };

  const restore = async (name: string) => {
    if (!confirm(`Restaurer ${name} ?`)) return;
    try {
      await restoreBackup(name);
      const fresh = await getConfig();
      setConfig(fresh);
    } catch (e) {
      setError(String(e));
    }
  };

  const TABS: { key: keyof FraudConfig; label: string }[] = [
    { key: "global", label: "Global" },
    { key: "ato", label: "ATO §3.2.1" },
    { key: "refund", label: "Refund §3.2.2" },
    { key: "fake_credentials", label: "Fake Cred §3.2.3" },
    { key: "split_deposit", label: "Split Dep §3.2.4" },
    { key: "smurfing", label: "Smurfing §3.2.5" },
  ];

  if (error) {
    return (
      <Layout title="Configuration" subtitle="fraudScenariosConfig.json">
        <div className="card border-red-900/50">
          <p className="text-accent-fraud text-sm">{error}</p>
        </div>
      </Layout>
    );
  }

  if (!config) {
    return (
      <Layout title="Configuration" subtitle="fraudScenariosConfig.json">
        <p className="text-text-muted text-sm">Chargement…</p>
      </Layout>
    );
  }

  const g = config.global;
  const a = config.ato;
  const r = config.refund;
  const fc = config.fake_credentials;
  const sd = config.split_deposit;
  const sm = config.smurfing;

  return (
    <Layout title="Configuration" subtitle="Édition de fraudScenariosConfig.json">
      <div className="grid grid-cols-1 xl:grid-cols-4 gap-6">
        {/* Panneau principal */}
        <div className="xl:col-span-3 space-y-4">
          {/* Tabs */}
          <div className="flex gap-1 flex-wrap">
            {TABS.map((t) => (
              <button
                key={t.key}
                onClick={() => setActiveTab(t.key)}
                className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors cursor-pointer ${
                  activeTab === t.key
                    ? "bg-accent-blue text-white"
                    : "bg-bg-card text-text-muted hover:text-text-primary border border-border"
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>

          {/* Champs par scénario */}
          <div className="card">
            {activeTab === "global" && (
              <div className="grid grid-cols-2 gap-4">
                <NumField label="fraud_target_min" path="global.fraud_target_min" value={g.fraud_target_min} onChange={set} min={0} max={1} isFloat />
                <NumField label="fraud_target_max" path="global.fraud_target_max" value={g.fraud_target_max} onChange={set} min={0} max={1} isFloat />
              </div>
            )}
            {activeTab === "ato" && (
              <div className="grid grid-cols-3 gap-4">
                <NumField label="B_min (FCFA)" path="ato.B_min" value={a.B_min} onChange={set} min={0} />
                <NumField label="n_min" path="ato.n_min" value={a.n_min} onChange={set} min={1} />
                <NumField label="n_max" path="ato.n_max" value={a.n_max} onChange={set} min={1} />
                <NumField label="frag_min" path="ato.frag_min" value={a.frag_min} onChange={set} min={0} max={1} isFloat />
                <NumField label="frag_max" path="ato.frag_max" value={a.frag_max} onChange={set} min={0} max={1} isFloat />
                <NumField label="lambda_ato" path="ato.lambda_ato" value={a.lambda_ato} onChange={set} min={0.1} isFloat />
              </div>
            )}
            {activeTab === "refund" && (
              <div className="grid grid-cols-3 gap-4">
                <NumField label="p_refund_threshold" path="refund.p_refund_threshold" value={r.p_refund_threshold} onChange={set} min={0} max={1} isFloat />
                <NumField label="delay_min_hours" path="refund.delay_min_hours" value={r.delay_min_hours} onChange={set} min={0} />
                <NumField label="delay_max_hours" path="refund.delay_max_hours" value={r.delay_max_hours} onChange={set} min={1} />
                <NumField label="k_max" path="refund.k_max" value={r.k_max} onChange={set} min={1} />
                <NumField label="ratio_legit" path="refund.ratio_legit" value={r.ratio_legit} onChange={set} min={0} max={1} isFloat />
              </div>
            )}
            {activeTab === "fake_credentials" && (
              <div className="grid grid-cols-3 gap-4">
                <NumField label="dormance_min_days" path="fake_credentials.dormance_min_days" value={fc.dormance_min_days} onChange={set} min={0} />
                <NumField label="dormance_max_days" path="fake_credentials.dormance_max_days" value={fc.dormance_max_days} onChange={set} min={1} />
                <NumField label="n_leg_min" path="fake_credentials.n_leg_min" value={fc.n_leg_min} onChange={set} min={0} />
                <NumField label="n_leg_max" path="fake_credentials.n_leg_max" value={fc.n_leg_max} onChange={set} min={1} />
                <NumField label="m_leg_max (FCFA)" path="fake_credentials.m_leg_max" value={fc.m_leg_max} onChange={set} min={0} />
                <NumField label="m_exp_ratio_min" path="fake_credentials.m_exp_ratio_min" value={fc.m_exp_ratio_min} onChange={set} min={0} max={1} isFloat />
              </div>
            )}
            {activeTab === "split_deposit" && (
              <div className="grid grid-cols-3 gap-4">
                <NumField label="epsilon_max (FCFA)" path="split_deposit.epsilon_max" value={sd.epsilon_max} onChange={set} min={0} />
                <NumField label="T_split_min_sec" path="split_deposit.T_split_min_sec" value={sd.T_split_min_sec} onChange={set} min={0} />
                <NumField label="T_split_max_sec" path="split_deposit.T_split_max_sec" value={sd.T_split_max_sec} onChange={set} min={1} />
                <div className="col-span-3">
                  <p className="label">Grille tarifaire (threshold / commission)</p>
                  <div className="mt-1 space-y-1">
                    {sd.tariff_grid.map((slot, i) => (
                      <div key={i} className="flex gap-2 items-center text-xs font-mono text-text-muted bg-bg-secondary rounded px-2 py-1">
                        <span>≥ {slot.threshold.toLocaleString("fr-FR")} FCFA</span>
                        <span className="text-text-dim">→</span>
                        <span>{slot.commission} FCFA</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}
            {activeTab === "smurfing" && (
              <div className="grid grid-cols-3 gap-4">
                <NumField label="n_mules_min" path="smurfing.n_mules_min" value={sm.n_mules_min} onChange={set} min={1} />
                <NumField label="n_mules_max" path="smurfing.n_mules_max" value={sm.n_mules_max} onChange={set} min={1} />
                <NumField label="pct_conscious" path="smurfing.pct_conscious" value={sm.pct_conscious} onChange={set} min={0} max={1} isFloat />
                <NumField label="S_seuil COBAC (FCFA)" path="smurfing.S_seuil" value={sm.S_seuil} onChange={set} min={0} />
                <NumField label="delta_min" path="smurfing.delta_min" value={sm.delta_min} onChange={set} min={0} max={1} isFloat />
                <NumField label="delta_max" path="smurfing.delta_max" value={sm.delta_max} onChange={set} min={0} max={1} isFloat />
                <NumField label="delay_mule_min_hours" path="smurfing.delay_mule_min_hours" value={sm.delay_mule_min_hours} onChange={set} min={0} />
                <NumField label="delay_mule_max_hours" path="smurfing.delay_mule_max_hours" value={sm.delay_mule_max_hours} onChange={set} min={1} />
                <NumField label="operation_interval_days" path="smurfing.operation_interval_days" value={sm.operation_interval_days} onChange={set} min={1} />
                <NumField label="n_leg_mule_min" path="smurfing.n_leg_mule_min" value={sm.n_leg_mule_min} onChange={set} min={0} />
                <NumField label="n_leg_mule_max" path="smurfing.n_leg_mule_max" value={sm.n_leg_mule_max} onChange={set} min={1} />
              </div>
            )}
          </div>

          {/* Actions */}
          <div className="flex gap-3 items-center">
            <button
              className="btn-primary text-sm"
              onClick={save}
              disabled={saving}
            >
              {saving ? "Sauvegarde…" : "Sauvegarder"}
            </button>
            {saved && <span className="text-accent-green text-sm">Sauvegardé ✓</span>}
            {error && <span className="text-accent-fraud text-sm">{error}</span>}
          </div>
        </div>

        {/* Backups */}
        <div className="xl:col-span-1">
          <div className="card">
            <h2 className="section-title">Backups</h2>
            <p className="section-subtitle">Créés automatiquement à chaque sauvegarde</p>
            {backups.length === 0 ? (
              <p className="text-xs text-text-dim">Aucun backup.</p>
            ) : (
              <div className="space-y-2">
                {backups.slice(0, 10).map((b) => (
                  <div key={b.name} className="flex items-center justify-between gap-2 py-1">
                    <div className="min-w-0">
                      <p className="text-2xs font-mono text-text-muted truncate">{b.name}</p>
                      <p className="text-2xs text-text-dim">{new Date(b.modified).toLocaleString("fr-FR")}</p>
                    </div>
                    <button
                      className="btn-secondary text-2xs px-2 py-1 flex-shrink-0"
                      onClick={() => restore(b.name)}
                    >
                      ↩
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
    </Layout>
  );
}
