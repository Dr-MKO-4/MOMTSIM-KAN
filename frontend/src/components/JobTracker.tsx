import { useEffect, useRef, useState } from "react";
import { pollJob } from "../api/client";
import type { Job } from "../types/api";

interface Props {
  jobId: string | null;
  onDone?: (result: Record<string, unknown>) => void;
  onError?: (err: string) => void;
}

export default function JobTracker({ jobId, onDone, onError }: Props) {
  const [job, setJob] = useState<Job | null>(null);
  const stopRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    if (stopRef.current) stopRef.current();
    if (!jobId) { setJob(null); return; }

    stopRef.current = pollJob(jobId, (j) => {
      setJob(j);
      if (j.status === "done" && j.result) onDone?.(j.result);
      if (j.status === "error") onError?.(j.error ?? "Erreur inconnue");
    });

    return () => { stopRef.current?.(); };
  }, [jobId]);

  if (!job) return null;

  const statusColor: Record<string, string> = {
    pending: "text-text-muted",
    running: "text-accent-blue",
    done: "text-accent-green",
    error: "text-accent-fraud",
  };

  return (
    <div className="card mt-4">
      <div className="flex items-center justify-between mb-2">
        <span className={`text-sm font-mono font-medium ${statusColor[job.status]}`}>
          {job.status.toUpperCase()}
        </span>
        <span className="text-xs text-text-dim font-mono">{job.progress}%</span>
      </div>

      {/* Progress bar */}
      <div className="w-full bg-bg-secondary rounded-full h-1.5 mb-2">
        <div
          className={`h-1.5 rounded-full transition-all duration-300 ${
            job.status === "error" ? "bg-accent-fraud" :
            job.status === "done"  ? "bg-accent-green" :
                                     "bg-accent-blue"
          }`}
          style={{ width: `${job.progress}%` }}
        />
      </div>

      <p className="text-xs text-text-muted">{job.message}</p>

      {job.status === "error" && job.error && (
        <pre className="mt-3 p-3 bg-red-950/30 border border-red-900/50 rounded text-2xs text-red-300 font-mono overflow-x-auto whitespace-pre-wrap">
          {job.error}
        </pre>
      )}
    </div>
  );
}
