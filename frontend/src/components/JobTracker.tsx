import { useEffect, useRef, useState } from "react";
import { Loader2, CheckCircle2, XCircle, Clock } from "lucide-react";
import { pollJob } from "../api/client";
import type { Job } from "../types/api";

interface Props {
  jobId: string | null;
  onDone?: (result: Record<string, unknown>) => void;
  onError?: (err: string) => void;
}

const STATUS_CONFIG = {
  pending: {
    label: "En attente",
    icon: Clock,
    barClass: "bg-text-dim animate-progress-pulse",
    textClass: "text-text-muted",
    iconClass: "text-text-dim",
  },
  running: {
    label: "En cours",
    icon: Loader2,
    barClass: "bg-accent-blue",
    textClass: "text-accent-blue",
    iconClass: "text-accent-blue animate-spin-slow",
  },
  done: {
    label: "Terminé",
    icon: CheckCircle2,
    barClass: "bg-accent-green",
    textClass: "text-accent-green",
    iconClass: "text-accent-green",
  },
  error: {
    label: "Erreur",
    icon: XCircle,
    barClass: "bg-accent-fraud",
    textClass: "text-accent-fraud",
    iconClass: "text-accent-fraud",
  },
} as const;

function formatElapsed(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}m ${s < 10 ? "0" : ""}${s}s`;
}

export default function JobTracker({ jobId, onDone, onError }: Props) {
  const [job, setJob] = useState<Job | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const stopRef  = useRef<(() => void) | null>(null);
  const startRef = useRef<number>(Date.now());

  useEffect(() => {
    stopRef.current?.();
    if (!jobId) { setJob(null); setElapsed(0); return; }

    startRef.current = Date.now();
    setElapsed(0);

    stopRef.current = pollJob(jobId, (j) => {
      setJob(j);
      if (j.status === "done" && j.result) onDone?.(j.result);
      if (j.status === "error")            onError?.(j.error ?? "Erreur inconnue");
    });

    return () => { stopRef.current?.(); };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  /* Elapsed timer — ticks only while pending/running */
  useEffect(() => {
    if (!job || job.status === "done" || job.status === "error") return;
    const id = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startRef.current) / 1000));
    }, 1000);
    return () => clearInterval(id);
  }, [job?.status]);

  if (!job) return null;

  const cfg = STATUS_CONFIG[job.status];
  const StatusIcon = cfg.icon;
  const isRunning  = job.status === "running" || job.status === "pending";

  return (
    <div className="card mt-4 animate-fade-in" role="status" aria-live="polite">
      {/* Header row */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <StatusIcon
            className={`w-4 h-4 flex-shrink-0 ${cfg.iconClass}`}
            aria-hidden="true"
          />
          <span className={`text-xs font-mono font-semibold ${cfg.textClass}`}>
            {cfg.label.toUpperCase()}
          </span>
        </div>
        <div className="flex items-center gap-3">
          {isRunning && (
            <span className="text-2xs text-text-dim font-mono" aria-label="Temps écoulé">
              {formatElapsed(elapsed)}
            </span>
          )}
          <span
            className={`text-xs font-mono font-medium ${cfg.textClass}`}
            aria-label={`Progression : ${job.progress} pourcent`}
          >
            {job.progress}%
          </span>
        </div>
      </div>

      {/* Progress bar */}
      <div
        className="w-full bg-bg-secondary rounded-full h-1 mb-3 overflow-hidden"
        role="progressbar"
        aria-valuenow={job.progress}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Progression du job"
      >
        <div
          className={`h-1 rounded-full transition-all duration-500 ease-out ${cfg.barClass}`}
          style={{ width: `${job.progress}%` }}
        />
      </div>

      {/* Message */}
      <p className="text-xs text-text-muted leading-relaxed">{job.message}</p>

      {/* Error detail */}
      {job.status === "error" && job.error && (
        <details className="mt-3">
          <summary className="text-2xs text-accent-fraud cursor-pointer hover:text-red-400 transition-colors duration-150 select-none">
            Détail de l'erreur
          </summary>
          <pre className="mt-2 p-3 bg-red-950/20 border border-red-900/40 rounded-lg text-2xs text-red-300 font-mono overflow-x-auto whitespace-pre-wrap leading-relaxed">
            {job.error}
          </pre>
        </details>
      )}
    </div>
  );
}
