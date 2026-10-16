import { useEffect, useRef, useState } from "react";
import {
  Loader2, CheckCircle2, XCircle, Clock, Square, RotateCcw, Timer, Hourglass, Circle,
} from "lucide-react";
import { pollJob, cancelJob } from "../api/client";
import type { Job, JobStage } from "../types/api";
import ProgressBar from "./ui/ProgressBar";

interface Props {
  jobId: string | null;
  title?: string;
  onDone?: (result: Record<string, unknown>) => void;
  onError?: (err: string) => void;
  onUpdate?: (job: Job) => void;
  onStop?: () => void;
  onRestart?: () => void;
}

const STATUS = {
  pending: { label: "En attente", icon: Clock,        tone: "gray"  as const, cls: "text-text-muted bg-slate-100" },
  running: { label: "En cours",   icon: Loader2,      tone: "brand" as const, cls: "text-accent-blue bg-indigo-50" },
  done:    { label: "Terminé",    icon: CheckCircle2, tone: "green" as const, cls: "text-accent-green bg-emerald-50" },
  error:   { label: "Erreur",     icon: XCircle,      tone: "red"   as const, cls: "text-accent-fraud bg-rose-50" },
};

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !isFinite(seconds) || seconds < 0) return "–";
  const s = Math.round(seconds);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  if (h) return `${h} h ${String(m).padStart(2, "0")} min`;
  if (m) return `${m} min ${String(r).padStart(2, "0")} s`;
  return `${r} s`;
}

const nf = new Intl.NumberFormat("fr-FR");
const pct = (v: number) => `${(v * 100).toFixed(1)} %`;

function metricChips(job: Job): { label: string; value: string }[] {
  const m = job.metrics ?? {};
  const out: { label: string; value: string }[] = [];
  const num = (k: string) => (typeof m[k] === "number" ? (m[k] as number) : null);
  if (job.kind === "simulation") {
    if (num("step") !== null) out.push({ label: "Pas", value: `${nf.format(num("step")!)} / ${nf.format(num("n_steps") ?? 0)}` });
    if (num("n_transactions") !== null) out.push({ label: "Transactions", value: nf.format(num("n_transactions")!) });
    if (num("fraud_rate") !== null) out.push({ label: "Fraude", value: pct(num("fraud_rate")!) });
    if (num("steps_per_s") !== null) out.push({ label: "Débit", value: `${num("steps_per_s")!.toFixed(1)} pas/s` });
  } else if (job.kind === "calibration") {
    if (num("sims_done") !== null) out.push({ label: "Simulations", value: `${Math.floor(num("sims_done")!)} / ${num("sims_total") ?? "?"}` });
    if (num("iteration") !== null) out.push({ label: "Itération", value: `${num("iteration")} / ${num("maxiter") ?? "?"}` });
    if (num("best_sse") !== null) out.push({ label: "Meilleure SSE", value: num("best_sse")!.toExponential(3) });
    if (num("fraud_rate") !== null) out.push({ label: "Fraude", value: pct(num("fraud_rate")!) });
    if (num("n_workers") !== null) out.push({ label: "Processus", value: String(num("n_workers")) });
  } else if (job.kind === "features") {
    if (num("n_rows") !== null) out.push({ label: "Transactions", value: nf.format(num("n_rows")!) });
  }
  return out;
}

function StageStepper({ stages }: { stages: JobStage[] }) {
  return (
    <ol className="flex flex-wrap items-center gap-x-1 gap-y-2" aria-label="Étapes">
      {stages.map((s, i) => {
        const Icon = s.status === "done" ? CheckCircle2
          : s.status === "running" ? Loader2
          : s.status === "error" ? XCircle : Circle;
        const cls = s.status === "done" ? "text-accent-green"
          : s.status === "running" ? "text-accent-blue"
          : s.status === "error" ? "text-accent-fraud" : "text-text-dim";
        return (
          <li key={s.key} className="flex items-center gap-1">
            <span className={`flex items-center gap-1.5 rounded-full px-2 py-1 text-2xs font-medium ${
              s.status === "running" ? "bg-indigo-50 ring-1 ring-indigo-200" : ""}`}>
              <Icon className={`w-3.5 h-3.5 ${cls} ${s.status === "running" ? "animate-spin-slow" : ""}`} aria-hidden="true" />
              <span className={s.status === "pending" ? "text-text-dim" : "text-text-muted"}>{s.label}</span>
            </span>
            {i < stages.length - 1 && <span className="w-4 h-px bg-border" aria-hidden="true" />}
          </li>
        );
      })}
    </ol>
  );
}

export default function JobTracker({ jobId, title, onDone, onError, onUpdate, onStop, onRestart }: Props) {
  const [job, setJob] = useState<Job | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const stopRef = useRef<(() => void) | null>(null);
  const syncRef = useRef<{ server: number; at: number }>({ server: 0, at: Date.now() });
  const cbRef = useRef({ onDone, onError, onUpdate });
  cbRef.current = { onDone, onError, onUpdate };

  useEffect(() => {
    stopRef.current?.();
    if (!jobId) { setJob(null); setElapsed(0); return; }
    let finished = false;
    stopRef.current = pollJob(jobId, (j) => {
      setJob(j);
      syncRef.current = { server: j.elapsed_s ?? 0, at: Date.now() };
      setElapsed(j.elapsed_s ?? 0);
      cbRef.current.onUpdate?.(j);
      if (!finished && j.status === "done" && j.result) { finished = true; cbRef.current.onDone?.(j.result); }
      if (!finished && j.status === "error") { finished = true; cbRef.current.onError?.(j.error ?? "Erreur inconnue"); }
    });
    return () => { stopRef.current?.(); };
  }, [jobId]);

  /* Horloge locale entre deux réponses du serveur */
  useEffect(() => {
    if (!job || job.status === "done" || job.status === "error") return;
    const id = setInterval(() => {
      const { server, at } = syncRef.current;
      setElapsed(server + (Date.now() - at) / 1000);
    }, 1000);
    return () => clearInterval(id);
  }, [job?.status]);

  if (!jobId) return null;
  if (!job) {
    return (
      <div className="card mt-4 animate-fade-in">
        <div className="flex items-center gap-2">
          <Loader2 className="w-4 h-4 text-text-dim animate-spin-slow" aria-hidden="true" />
          <span className="text-xs text-text-dim">Connexion au job…</span>
        </div>
        <ProgressBar value={0} indeterminate size="sm" tone="gray" className="mt-3" />
      </div>
    );
  }

  const cfg = STATUS[job.status];
  const StatusIcon = cfg.icon;
  const isRunning = job.status === "running" || job.status === "pending";
  const chips = metricChips(job);
  const stop = onStop ?? (() => { cancelJob(job.job_id).catch(() => {}); });

  return (
    <div className="card mt-4 animate-fade-in space-y-4" role="status" aria-live="polite">
      {/* En-tête */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2.5 min-w-0">
          <span className={`relative flex h-8 w-8 items-center justify-center rounded-xl ${cfg.cls}`}>
            {isRunning && <span className="absolute inset-0 rounded-xl bg-indigo-300/40 animate-ping-soft" aria-hidden="true" />}
            <StatusIcon className={`relative w-4 h-4 ${job.status === "running" ? "animate-spin-slow" : ""}`} aria-hidden="true" />
          </span>
          <div className="min-w-0">
            <p className="text-sm font-semibold text-text-primary leading-tight">{title ?? "Tâche"}</p>
            <p className="text-2xs text-text-dim">{cfg.label}</p>
          </div>
        </div>
        <div className="flex items-center gap-1">
          {isRunning && (
            <button className="btn-sm btn-outline hover:text-accent-fraud hover:border-rose-300" onClick={stop} title="Arrêter le job">
              <Square className="w-3 h-3" aria-hidden="true" /> Arrêter
            </button>
          )}
          {!isRunning && onRestart && (
            <button className="btn-sm btn-outline" onClick={onRestart} title="Relancer">
              <RotateCcw className="w-3 h-3" aria-hidden="true" /> Relancer
            </button>
          )}
        </div>
      </div>

      {/* Progression */}
      <div>
        <div className="flex items-end justify-between mb-1.5">
          <span className="text-3xl font-semibold font-mono tracking-tight text-text-primary leading-none">
            {job.progress}<span className="text-base text-text-dim">%</span>
          </span>
          <div className="flex items-center gap-3 text-2xs text-text-muted font-mono">
            <span className="flex items-center gap-1" title="Temps écoulé">
              <Timer className="w-3 h-3" aria-hidden="true" /> {formatDuration(elapsed)}
            </span>
            {isRunning && (
              <span className="flex items-center gap-1" title="Temps restant estimé">
                <Hourglass className="w-3 h-3" aria-hidden="true" />
                {job.eta_s !== null && job.eta_s !== undefined ? `reste ~${formatDuration(job.eta_s)}` : "estimation…"}
              </span>
            )}
          </div>
        </div>
        <ProgressBar
          value={job.progress}
          tone={cfg.tone}
          size="lg"
          striped={job.status === "running"}
          indeterminate={isRunning && !!job.indeterminate}
          label="Progression du job"
        />
        <p className="text-xs text-text-muted leading-relaxed mt-2 min-h-[1.25rem]">{job.message}</p>
      </div>

      {/* Étapes */}
      {job.stages && job.stages.length > 0 && <StageStepper stages={job.stages} />}

      {/* Métriques en direct */}
      {chips.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
          {chips.map((c) => (
            <div key={c.label} className="rounded-lg bg-bg-sunken/70 px-2.5 py-1.5">
              <p className="text-2xs text-text-dim">{c.label}</p>
              <p className="text-xs font-mono font-medium text-text-primary truncate">{c.value}</p>
            </div>
          ))}
        </div>
      )}

      {/* Détail de l'erreur */}
      {job.status === "error" && job.error && job.error !== "Annulé" && (
        <details>
          <summary className="text-2xs text-accent-fraud cursor-pointer select-none">Détail de l'erreur</summary>
          <pre className="mt-2 p-3 bg-rose-50 border border-rose-200 rounded-lg text-2xs text-rose-800 font-mono overflow-x-auto whitespace-pre-wrap leading-relaxed max-h-64">
            {job.error}
          </pre>
        </details>
      )}
    </div>
  );
}
