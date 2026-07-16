import { useCallback, useEffect, useId, useState } from "react";
import { Save, RotateCcw, CheckCircle2, AlertCircle, Info } from "lucide-react";
import Layout from "../components/Layout";
import FormField from "../components/ui/FormField";
import { getConfig, updateConfig, listBackups, restoreBackup } from "../api/client";
import type { FraudConfig, BackupEntry } from "../types/api";

/* ── Nested object setter ───────────────────────────────────────────────── */
function setNested(
  obj: Record<string, unknown>,
  path: string,
  val: unknown
): Record<string, unknown> {
  const keys  = path.split(".");
  const result = { ...obj };
  let cursor: Record<string, unknown> = result;
  for (let i = 0; i < keys.length - 1; i++) {
    cursor[keys[i]] = { ...(cursor[keys[i]] as Record<string, unknown>) };
    cursor = cursor[keys[i]] as Record<string, unknown>;
  }
  cursor[keys[keys.length - 1]] = val;
  return result;
}

/* ── Scenario info ──────────────────────────────────────────────────────── */
const SCENARIO_INFO: Record<string, {
  title: string; section: string; description: string; bullets: string[];
}> = {
  global: {
    title: "Paramètres globaux",
    section: "§3.1.3",
    description: "Cibles de calibration SPSA. Ces bornes définissent le taux de fraude acceptable en sortie de simulation.",
    bullets: [
      "Le calibrateur SPSA ajuste θ pour que le taux simulé se situe dans [min, max]",
      "Valeurs recommandées : [0.20, 0.26] — cible mémoire = 0.23",
    ],
  },
  ato: {
    title: "Account Takeover (ATO)",
    section: "§3.2.1",
    description: "Prise de contrôle d'un compte légitime. L'attaquant vide le solde en plusieurs virements fractionnés vers des mules.",
    bullets: [
      "Cibles : clients dont le solde dépasse B_min",
      "Montant prélevé : fraction ∈ [frag_min, frag_max] du solde",
      "Arrivées d'attaques modélisées par un processus de Poisson (λ_ATO)",
    ],
  },
  refund: {
    title: "Fraude au remboursement (Refund)",
    section: "§3.2.2",
    description: "L'attaquant exploite la politique de remboursement d'un marchand vulnérable pour récupérer des fonds frauduleusement.",
    bullets: [
      "Sélectionne des marchands avec probabilité p_refund_threshold",
      "Répète jusqu'à k_max cycles achat → remboursement",
      "Intercale ratio_legit transactions légitimes pour masquer la fraude",
    ],
  },
  fake_credentials: {
    title: "Faux compte (Fake Credentials)",
    section: "§3.2.3",
    description: "Création d'un compte avec de fausses identités. Le compte reste dormant, se légitimise, puis explose brutalement.",
    bullets: [
      "Dormance : dormance_min à dormance_max jours sans activité",
      "Légitimation : n_leg_min–n_leg_max petites transactions",
      "Activation : explosion du solde (fraction ≥ m_exp_ratio_min)",
    ],
  },
  split_deposit: {
    title: "Dépôt fractionné (Split Deposit)",
    section: "§3.2.4",
    description: "Fractionnement de dépôts pour rester sous le seuil COBAC de déclaration. Chaque fragment est légèrement bruité (ε).",
    bullets: [
      "Chaque dépôt = S_COBAC − ε, avec ε ∈ [0, epsilon_max]",
      "Intervalle entre fragments : T_split_min à T_split_max secondes",
      "Granularité réelle : 1 step = 1 h — arrondis inévitables en simulation",
    ],
  },
  smurfing: {
    title: "Smurfing (réseau de mules)",
    section: "§3.2.5",
    description: "Blanchiment via un réseau de mules. Un donneur d'ordre collecte des fonds illicites redistribués en fragments sous le seuil COBAC.",
    bullets: [
      "Réseau : n_mules_min à n_mules_max mules par opération",
      "Mules conscientes (pct_conscious) vs. involontaires",
      "Commission δ ∈ [delta_min, delta_max] du montant versée à chaque mule",
      "Chaque fragment reste sous S_seuil COBAC (éq. 3.13)",
    ],
  },
};

/* ── Scenario banner ────────────────────────────────────────────────────── */
function ScenarioBanner({ tab }: { tab: keyof FraudConfig }) {
  const info = SCENARIO_INFO[tab as string];
  if (!info) return null;
  return (
    <div className="mb-5 p-4 rounded-xl border border-accent-blue/20 bg-accent-blue/5">
      <div className="flex items-start gap-3">
        <Info className="w-4 h-4 text-accent-blue flex-shrink-0 mt-0.5" aria-hidden="true" />
        <div>
          <div className="flex items-center gap-2 mb-1.5">
            <h3 className="text-sm font-semibold text-text-primary">{info.title}</h3>
            <span className="text-2xs font-mono text-accent-blue bg-accent-blue/10 px-2 py-0.5 rounded">
              {info.section}
            </span>
          </div>
          <p className="text-xs text-text-muted mb-2 leading-relaxed">{info.description}</p>
          <ul className="space-y-0.5">
            {info.bullets.map((b, i) => (
              <li key={i} className="text-2xs text-text-dim flex gap-1.5 leading-relaxed">
                <span className="text-accent-blue flex-shrink-0 mt-px">·</span>
                {b}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}

/* ── Tabs ───────────────────────────────────────────────────────────────── */
const TABS: { key: keyof FraudConfig; label: string; section: string }[] = [
  { key: "global",           label: "Global",     section: "" },
  { key: "ato",              label: "ATO",        section: "§3.2.1" },
  { key: "refund",           label: "Refund",     section: "§3.2.2" },
  { key: "fake_credentials", label: "Fake Cred",  section: "§3.2.3" },
  { key: "split_deposit",    label: "Split Dep",  section: "§3.2.4" },
  { key: "smurfing",         label: "Smurfing",   section: "§3.2.5" },
];

/* ── Page ───────────────────────────────────────────────────────────────── */
export default function ConfigPage() {
  const [config, setConfig]       = useState<FraudConfig | null>(null);
  const [saving, setSaving]       = useState(false);
  const [saved, setSaved]         = useState(false);
  const [error, setError]         = useState<string | null>(null);
  const [backups, setBackups]     = useState<BackupEntry[]>([]);
  const [activeTab, setActiveTab] = useState<keyof FraudConfig>("global");
  const confirmId = useId();

  const loadData = useCallback(() => {
    getConfig().then(setConfig).catch((e) => setError(String(e)));
    listBackups().then(setBackups).catch(() => null);
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  const set = useCallback((path: string, val: number) => {
    setConfig((prev) => {
      if (!prev) return prev;
      return setNested(prev as unknown as Record<string, unknown>, path, val) as unknown as FraudConfig;
    });
  }, []);

  const save = useCallback(async () => {
    if (!config) return;
    setSaving(true);
    setError(null);
    try {
      await updateConfig(config);
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
      listBackups().then(setBackups);
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  }, [config]);

  const restore = useCallback(async (name: string) => {
    if (!window.confirm(`Restaurer "${name}" ?`)) return;
    try {
      await restoreBackup(name);
      const fresh = await getConfig();
      setConfig(fresh);
    } catch (e) {
      setError(String(e));
    }
  }, []);

  if (error && !config) {
    return (
      <Layout title="Configuration" subtitle="fraudScenariosConfig.json">
        <div className="card border-accent-fraud/40">
          <div className="flex items-center gap-2 mb-2">
            <AlertCircle className="w-4 h-4 text-accent-fraud" aria-hidden="true" />
            <p className="section-title text-accent-fraud">Erreur de chargement</p>
          </div>
          <p className="text-sm text-text-muted">{error}</p>
        </div>
      </Layout>
    );
  }

  if (!config) {
    return (
      <Layout title="Configuration" subtitle="fraudScenariosConfig.json">
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="card h-32 animate-pulse bg-bg-secondary" />
          ))}
        </div>
      </Layout>
    );
  }

  const g  = config.global;
  const a  = config.ato;
  const r  = config.refund;
  const fc = config.fake_credentials;
  const sd = config.split_deposit;
  const sm = config.smurfing;

  return (
    <Layout title="Configuration" subtitle="Édition de fraudScenariosConfig.json">
      <div className="grid grid-cols-1 xl:grid-cols-4 gap-5">
        {/* ── Main panel ────────────────────────────────────────────── */}
        <div className="xl:col-span-3 space-y-4">
          {/* Tabs */}
          <div className="flex gap-1.5 flex-wrap" role="tablist" aria-label="Scénarios de configuration">
            {TABS.map((t) => (
              <button
                key={t.key}
                role="tab"
                aria-selected={activeTab === t.key}
                aria-controls={`tab-panel-${t.key}`}
                onClick={() => setActiveTab(t.key)}
                className={[
                  "px-3 py-1.5 rounded-lg text-xs font-medium transition-colors duration-150 cursor-pointer",
                  activeTab === t.key
                    ? "bg-accent-blue text-white"
                    : "bg-bg-card text-text-muted hover:text-text-primary border border-border hover:border-border-hover",
                ].join(" ")}
              >
                {t.label}
                {t.section && (
                  <span className={`ml-1.5 text-2xs font-mono ${
                    activeTab === t.key ? "text-blue-200" : "text-text-dim"
                  }`}>
                    {t.section}
                  </span>
                )}
              </button>
            ))}
          </div>

          {/* Fields */}
          <div
            className="card"
            role="tabpanel"
            id={`tab-panel-${activeTab}`}
            aria-labelledby={`tab-${activeTab}`}
          >
            <ScenarioBanner tab={activeTab} />

            {activeTab === "global" && (
              <div className="grid grid-cols-2 gap-4">
                <FormField
                  label="Taux minimal de fraude"
                  name="global.fraud_target_min"
                  value={g.fraud_target_min}
                  onChange={set}
                  min={0} max={1} isFloat
                  hint="Borne inférieure du taux cible pour la calibration SPSA [0–1]"
                />
                <FormField
                  label="Taux maximal de fraude"
                  name="global.fraud_target_max"
                  value={g.fraud_target_max}
                  onChange={set}
                  min={0} max={1} isFloat
                  hint="Borne supérieure du taux cible pour la calibration SPSA [0–1]"
                />
              </div>
            )}

            {activeTab === "ato" && (
              <div className="grid grid-cols-3 gap-4">
                <FormField
                  label="Solde minimum victime (FCFA)"
                  name="ato.B_min"
                  value={a.B_min}
                  onChange={set}
                  min={0}
                  hint="Solde requis pour être ciblé — les clients sous ce seuil sont ignorés"
                />
                <FormField
                  label="Virements frauduleux min."
                  name="ato.n_min"
                  value={a.n_min}
                  onChange={set}
                  min={1}
                  hint="Nombre minimal de transferts vers des mules par attaque"
                />
                <FormField
                  label="Virements frauduleux max."
                  name="ato.n_max"
                  value={a.n_max}
                  onChange={set}
                  min={1}
                  hint="Nombre maximal de transferts vers des mules par attaque"
                />
                <FormField
                  label="Fraction prélevée min."
                  name="ato.frag_min"
                  value={a.frag_min}
                  onChange={set}
                  min={0} max={1} isFloat
                  hint="Part minimale du solde victime extorquée par attaque [0–1]"
                />
                <FormField
                  label="Fraction prélevée max."
                  name="ato.frag_max"
                  value={a.frag_max}
                  onChange={set}
                  min={0} max={1} isFloat
                  hint="Part maximale du solde victime extorquée par attaque [0–1]"
                />
                <FormField
                  label="Intensité λ_ATO (Poisson)"
                  name="ato.lambda_ato"
                  value={a.lambda_ato}
                  onChange={set}
                  min={0.1} isFloat
                  hint="Paramètre λ du processus de Poisson — fréquence d'attaques par step horaire"
                />
              </div>
            )}

            {activeTab === "refund" && (
              <div className="grid grid-cols-3 gap-4">
                <FormField
                  label="Vulnérabilité marchand"
                  name="refund.p_refund_threshold"
                  value={r.p_refund_threshold}
                  onChange={set}
                  min={0} max={1} isFloat
                  hint="Probabilité qu'un marchand accepte des demandes de remboursement frauduleuses [0–1]"
                />
                <FormField
                  label="Délai remboursement min. (h)"
                  name="refund.delay_min_hours"
                  value={r.delay_min_hours}
                  onChange={set}
                  min={0}
                  hint="Délai minimal avant que l'attaquant demande le remboursement"
                />
                <FormField
                  label="Délai remboursement max. (h)"
                  name="refund.delay_max_hours"
                  value={r.delay_max_hours}
                  onChange={set}
                  min={1}
                  hint="Délai maximal avant que l'attaquant demande le remboursement"
                />
                <FormField
                  label="Cycles max. par marchand"
                  name="refund.k_max"
                  value={r.k_max}
                  onChange={set}
                  min={1}
                  hint="Nombre maximal de cycles achat → remboursement exploités par marchand"
                />
                <FormField
                  label="Camouflage (tx légitimes)"
                  name="refund.ratio_legit"
                  value={r.ratio_legit}
                  onChange={set}
                  min={0} max={1} isFloat
                  hint="Part de transactions légitimes intercalées pour diluer le signal frauduleux [0–1]"
                />
              </div>
            )}

            {activeTab === "fake_credentials" && (
              <div className="grid grid-cols-3 gap-4">
                <FormField
                  label="Dormance min. (jours)"
                  name="fake_credentials.dormance_min_days"
                  value={fc.dormance_min_days}
                  onChange={set}
                  min={0}
                  hint="Durée minimale d'inactivité du faux compte avant la phase de légitimation"
                />
                <FormField
                  label="Dormance max. (jours)"
                  name="fake_credentials.dormance_max_days"
                  value={fc.dormance_max_days}
                  onChange={set}
                  min={1}
                  hint="Durée maximale d'inactivité avant que le compte commence à agir"
                />
                <FormField
                  label="Tx légitimes min. (phase lég.)"
                  name="fake_credentials.n_leg_min"
                  value={fc.n_leg_min}
                  onChange={set}
                  min={0}
                  hint="Nombre minimal de transactions légitimes pour crédibiliser le faux compte"
                />
                <FormField
                  label="Tx légitimes max. (phase lég.)"
                  name="fake_credentials.n_leg_max"
                  value={fc.n_leg_max}
                  onChange={set}
                  min={1}
                  hint="Nombre maximal de transactions légitimes avant l'activation frauduleuse"
                />
                <FormField
                  label="Montant légitimes max. (FCFA)"
                  name="fake_credentials.m_leg_max"
                  value={fc.m_leg_max}
                  onChange={set}
                  min={0}
                  hint="Plafond des montants pour les transactions de légitimation"
                />
                <FormField
                  label="Ratio activation min."
                  name="fake_credentials.m_exp_ratio_min"
                  value={fc.m_exp_ratio_min}
                  onChange={set}
                  min={0} max={1} isFloat
                  hint="Fraction minimale du solde explosée lors de l'activation frauduleuse [0–1]"
                />
              </div>
            )}

            {activeTab === "split_deposit" && (
              <div className="space-y-4">
                <div className="grid grid-cols-3 gap-4">
                  <FormField
                    label="Bruit ε_max (FCFA)"
                    name="split_deposit.epsilon_max"
                    value={sd.epsilon_max}
                    onChange={set}
                    min={0}
                    hint="Bruit aléatoire maximal soustrait à chaque fragment pour rester sous le seuil COBAC"
                  />
                  <FormField
                    label="Intervalle fragments min. (sec)"
                    name="split_deposit.T_split_min_sec"
                    value={sd.T_split_min_sec}
                    onChange={set}
                    min={0}
                    hint="Délai minimal entre deux dépôts fractionnés (en secondes réelles)"
                  />
                  <FormField
                    label="Intervalle fragments max. (sec)"
                    name="split_deposit.T_split_max_sec"
                    value={sd.T_split_max_sec}
                    onChange={set}
                    min={1}
                    hint="Délai maximal entre deux dépôts — arrondi à 1 step = 1 h en simulation"
                  />
                </div>
                <div>
                  <p className="label">Grille tarifaire (lecture seule)</p>
                  <p className="text-2xs text-text-dim mb-2">
                    Seuils COBAC utilisés pour le calcul de delta_commission — éq. 3.13
                  </p>
                  <div className="mt-1.5 space-y-1 rounded-lg overflow-hidden border border-border">
                    <div className="grid grid-cols-2 bg-bg-secondary px-3 py-1.5">
                      <span className="table-th border-0 px-0 py-0 text-2xs">Seuil</span>
                      <span className="table-th border-0 px-0 py-0 text-2xs text-right">Commission</span>
                    </div>
                    {sd.tariff_grid.map((slot, i) => (
                      <div
                        key={i}
                        className="grid grid-cols-2 px-3 py-1.5 border-t border-border/40 hover:bg-bg-hover transition-colors duration-100"
                      >
                        <span className="text-xs font-mono text-text-muted">
                          ≥ {slot.threshold.toLocaleString("fr-FR")} FCFA
                        </span>
                        <span className="text-xs font-mono text-text-muted text-right">
                          {slot.commission} FCFA
                        </span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>
            )}

            {activeTab === "smurfing" && (
              <div className="grid grid-cols-3 gap-4">
                <FormField
                  label="Mules min. par réseau"
                  name="smurfing.n_mules_min"
                  value={sm.n_mules_min}
                  onChange={set}
                  min={1}
                  hint="Nombre minimal de mules impliquées par opération de blanchiment"
                />
                <FormField
                  label="Mules max. par réseau"
                  name="smurfing.n_mules_max"
                  value={sm.n_mules_max}
                  onChange={set}
                  min={1}
                  hint="Nombre maximal de mules impliquées par opération de blanchiment"
                />
                <FormField
                  label="Part mules conscientes"
                  name="smurfing.pct_conscious"
                  value={sm.pct_conscious}
                  onChange={set}
                  min={0} max={1} isFloat
                  hint="Fraction de mules sachant participer à un blanchiment (vs. mules involontaires) [0–1]"
                />
                <FormField
                  label="Seuil COBAC (FCFA)"
                  name="smurfing.S_seuil"
                  value={sm.S_seuil}
                  onChange={set}
                  min={0}
                  hint="Montant réglementaire à ne pas dépasser — chaque fragment reste sous ce seuil"
                />
                <FormField
                  label="Commission mule min."
                  name="smurfing.delta_min"
                  value={sm.delta_min}
                  onChange={set}
                  min={0} max={1} isFloat
                  hint="Rémunération minimale versée à la mule (fraction du montant transféré) [0–1]"
                />
                <FormField
                  label="Commission mule max."
                  name="smurfing.delta_max"
                  value={sm.delta_max}
                  onChange={set}
                  min={0} max={1} isFloat
                  hint="Rémunération maximale versée à la mule (fraction du montant transféré) [0–1]"
                />
                <FormField
                  label="Délai transfert mule min. (h)"
                  name="smurfing.delay_mule_min_hours"
                  value={sm.delay_mule_min_hours}
                  onChange={set}
                  min={0}
                  hint="Délai minimal avant que la mule reverse les fonds au donneur d'ordre"
                />
                <FormField
                  label="Délai transfert mule max. (h)"
                  name="smurfing.delay_mule_max_hours"
                  value={sm.delay_mule_max_hours}
                  onChange={set}
                  min={1}
                  hint="Délai maximal avant que la mule reverse les fonds au donneur d'ordre"
                />
                <FormField
                  label="Intervalle opération (jours)"
                  name="smurfing.operation_interval_days"
                  value={sm.operation_interval_days}
                  onChange={set}
                  min={1}
                  hint="Fréquence des cycles complets de smurfing (en jours simulés)"
                />
                <FormField
                  label="Tx légitimes mule min."
                  name="smurfing.n_leg_mule_min"
                  value={sm.n_leg_mule_min}
                  onChange={set}
                  min={0}
                  hint="Transactions légitimes minimales effectuées par chaque mule pour crédibilité"
                />
                <FormField
                  label="Tx légitimes mule max."
                  name="smurfing.n_leg_mule_max"
                  value={sm.n_leg_mule_max}
                  onChange={set}
                  min={1}
                  hint="Transactions légitimes maximales effectuées par chaque mule"
                />
              </div>
            )}
          </div>

          {/* Save bar */}
          <div className="flex items-center gap-3 flex-wrap">
            <button
              className="btn-primary"
              onClick={save}
              disabled={saving}
              aria-busy={saving}
            >
              {saving ? (
                <><Save className="w-4 h-4 animate-spin-slow" aria-hidden="true" />Sauvegarde…</>
              ) : (
                <><Save className="w-4 h-4" aria-hidden="true" />Sauvegarder</>
              )}
            </button>
            {saved && (
              <span className="flex items-center gap-1.5 text-sm text-accent-green" role="status">
                <CheckCircle2 className="w-4 h-4" aria-hidden="true" />
                Sauvegardé
              </span>
            )}
            {error && (
              <span className="flex items-center gap-1.5 text-sm text-accent-fraud" role="alert">
                <AlertCircle className="w-4 h-4" aria-hidden="true" />
                {error}
              </span>
            )}
          </div>
        </div>

        {/* ── Backups panel ─────────────────────────────────────────── */}
        <div className="xl:col-span-1">
          <div className="card" aria-labelledby={`${confirmId}-backups`}>
            <h2 id={`${confirmId}-backups`} className="section-title mb-0.5">Backups</h2>
            <p className="text-xs text-text-muted mb-3">Créés automatiquement à chaque sauvegarde</p>
            {backups.length === 0 ? (
              <p className="text-xs text-text-dim">Aucun backup disponible.</p>
            ) : (
              <div className="space-y-1.5">
                {backups.slice(0, 10).map((b) => (
                  <div key={b.name} className="flex items-center gap-2 py-1.5 border-b border-border/40 last:border-0">
                    <div className="min-w-0 flex-1">
                      <p className="text-2xs font-mono text-text-muted truncate">{b.name}</p>
                      <p className="text-2xs text-text-dim mt-0.5">
                        {new Date(b.modified).toLocaleString("fr-FR", { dateStyle: "short", timeStyle: "short" })}
                      </p>
                    </div>
                    <button
                      className="btn-outline btn-sm flex-shrink-0 px-2 py-1"
                      onClick={() => restore(b.name)}
                      aria-label={`Restaurer ${b.name}`}
                    >
                      <RotateCcw className="w-3 h-3" aria-hidden="true" />
                    </button>
                  </div>
                ))}
                {backups.length > 10 && (
                  <p className="text-2xs text-text-dim text-center pt-1">
                    +{backups.length - 10} autres
                  </p>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </Layout>
  );
}
