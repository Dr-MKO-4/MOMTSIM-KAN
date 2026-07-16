// Types miroirs des schémas Pydantic du backend

export interface GlobalConfig {
  fraud_target_min: number;
  fraud_target_max: number;
  scenarios_equal_share: boolean;
}

export interface ATOConfig {
  B_min: number;
  n_min: number;
  n_max: number;
  frag_min: number;
  frag_max: number;
  lambda_ato: number;
}

export interface RefundConfig {
  p_refund_threshold: number;
  delay_min_hours: number;
  delay_max_hours: number;
  k_max: number;
  ratio_legit: number;
}

export interface FakeCredentialsConfig {
  dormance_min_days: number;
  dormance_max_days: number;
  n_leg_min: number;
  n_leg_max: number;
  m_leg_max: number;
  m_exp_ratio_min: number;
}

export interface TariffSlot {
  threshold: number;
  commission: number;
}

export interface SplitDepositConfig {
  epsilon_max: number;
  T_split_min_sec: number;
  T_split_max_sec: number;
  tariff_grid: TariffSlot[];
}

export interface SmurfingConfig {
  n_mules_min: number;
  n_mules_max: number;
  pct_conscious: number;
  pct_unconscious: number;
  S_seuil: number;
  delta_min: number;
  delta_max: number;
  delay_mule_min_hours: number;
  delay_mule_max_hours: number;
  operation_interval_days: number;
  n_leg_mule_min: number;
  n_leg_mule_max: number;
}

export interface FraudConfig {
  global: GlobalConfig;
  ato: ATOConfig;
  refund: RefundConfig;
  fake_credentials: FakeCredentialsConfig;
  split_deposit: SplitDepositConfig;
  smurfing: SmurfingConfig;
}

export interface SimulationParams {
  n_clients: number;
  n_merchants: number;
  n_banks: number;
  n_mules: number;
  n_steps: number;
  max_slots: number;
  seed: number;
  fraud_probas: Record<string, number> | null;
}

export interface CalibrationParams {
  n_clients: number;
  n_merchants: number;
  n_banks: number;
  n_mules: number;
  target_mid: number;
  n_steps: number;
  n_bins: number;
  n_seeds_per_eval: number;
  maxiter: number;
  lr: number;
  spsa_c: number;
}

export type JobStatus = "pending" | "running" | "done" | "error";

export interface Job {
  job_id: string;
  status: JobStatus;
  progress: number;
  message: string;
  result: Record<string, unknown> | null;
  error: string | null;
}

export interface SimulationResult {
  n_transactions: number;
  fraud_rate: number;
  fraud_by_scenario: Record<string, number>;
  steps_run: number;
  csv_path: string;
  plain_summary?: string;
  charts: Record<string, string>;
}

export interface FeatureResult {
  n_rows: number;
  n_features: number;
  feature_names: string[];
  csv_path: string;
  charts: Record<string, string>;
}

export interface KANValidationResult {
  VE2: number;
  J_Fisher: number;
  D_KS_mean: number;
  k_for_VE80: number;
  decision: string;
  features_needing_transform: string[];
  features_poor_coverage: string[];
  ks_per_feature: Record<string, number>;
  grid_coverage: Record<string, number>;
  plain_summary?: string;
  charts: Record<string, string>;
}

export interface CalibrationResult {
  probas: Record<string, number>;
  sse_final: number;
  converged: boolean;
  history: Array<{ iter: number; sse: number; theta: number[] }>;
}

export interface HealthStatus {
  status: string;
  files: {
    fraudScenariosConfig: boolean;
    rawLog_torch: boolean;
    featuresLog: boolean;
    calibrated_probas: boolean;
  };
}

export interface BackupEntry {
  name: string;
  path: string;
  size: number;
  modified: string;
}

// ── BLOC C : Historique des runs ─────────────────────────────────────────

export interface RunSummary {
  n_transactions?: number;
  fraud_rate?: number;
  fraud_by_scenario?: Record<string, number>;
  n_rows?: number;
  n_features?: number;
  decision?: string;
  VE2?: number;
  J_Fisher?: number;
  D_KS_mean?: number;
  sse_final?: number;
  converged?: boolean;
  plain_summary?: string;
}

export interface RunEntry {
  id: string;
  run_type: "simulation" | "features" | "kan" | "calibration";
  timestamp: string;
  folder: string;
  summary: RunSummary;
}

export interface RunDetail extends RunEntry {
  metadata: Record<string, unknown>;
}

// ── BLOC A5 : Données paginées ───────────────────────────────────────────

export interface DataPage {
  page: number;
  page_size: number;
  total: number;
  total_pages: number;
  columns: string[];
  rows: (string | number | boolean | null)[][];
}

export interface FraudstersData {
  total: number;
  columns: string[];
  rows: (string | number | null)[][];
}
