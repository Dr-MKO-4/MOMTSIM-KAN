import type {
  FraudConfig, SimulationParams, CalibrationParams,
  Job, HealthStatus, BackupEntry,
} from "../types/api";

const BASE = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new Error(`${res.status} ${res.statusText}: ${text}`);
  }
  return res.json() as Promise<T>;
}

// --- Config ---
export const getConfig = () => request<FraudConfig>("/config");
export const updateConfig = (data: FraudConfig) =>
  request<{ saved: string }>("/config", { method: "PUT", body: JSON.stringify(data) });
export const listBackups = () => request<BackupEntry[]>("/config/backups");
export const restoreBackup = (name: string) =>
  request<{ restored: string }>(`/config/restore/${encodeURIComponent(name)}`, { method: "POST" });

// --- Probas ---
export const getProbas = () => request<Record<string, number>>("/probas");

// --- Jobs ---
export const getJob = (id: string) => request<Job>(`/jobs/${id}`);
export const listJobs = () => request<Job[]>("/jobs");

// --- Pipeline ---
export const startSimulation = (params: SimulationParams) =>
  request<{ job_id: string }>("/simulate", { method: "POST", body: JSON.stringify(params) });

export const startFeatures = () =>
  request<{ job_id: string }>("/features", { method: "POST" });

export const startKANValidation = () =>
  request<{ job_id: string }>("/kan/validate", { method: "POST" });

export const startCalibration = (params: CalibrationParams) =>
  request<{ job_id: string }>("/calibrate", { method: "POST", body: JSON.stringify(params) });

// --- Health ---
export const getHealth = () => request<HealthStatus>("/health");

// --- Polling helper ---
export function pollJob(
  jobId: string,
  onUpdate: (job: Job) => void,
  intervalMs = 1000
): () => void {
  let active = true;
  const tick = async () => {
    if (!active) return;
    try {
      const job = await getJob(jobId);
      onUpdate(job);
      if (job.status === "done" || job.status === "error") return;
    } catch (_) {
      // réseau temporairement indispo — on continue
    }
    setTimeout(tick, intervalMs);
  };
  tick();
  return () => { active = false; };
}
