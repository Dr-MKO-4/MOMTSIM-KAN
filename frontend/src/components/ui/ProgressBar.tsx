import { memo } from "react";

export type ProgressTone = "brand" | "green" | "red" | "amber" | "gray";

const FILL: Record<ProgressTone, string> = {
  brand: "bg-brand-gradient",
  green: "bg-gradient-to-r from-emerald-500 to-teal-400",
  red:   "bg-gradient-to-r from-rose-600 to-rose-400",
  amber: "bg-gradient-to-r from-amber-500 to-orange-400",
  gray:  "bg-slate-300",
};

interface Props {
  value: number;               // 0 – 100
  tone?: ProgressTone;
  size?: "xs" | "sm" | "md" | "lg";
  indeterminate?: boolean;     // étape sans progression mesurable : barre animée
  striped?: boolean;           // en cours : rayures animées
  animated?: boolean;          // reflet animé
  label?: string;
  className?: string;
}

const HEIGHT = { xs: "h-1", sm: "h-1.5", md: "h-2.5", lg: "h-3.5" };

function ProgressBar({
  value, tone = "brand", size = "md", indeterminate = false, striped = false,
  animated = true, label, className = "",
}: Props) {
  const pct = Math.max(0, Math.min(100, value));
  return (
    <div
      className={`progress-track ${HEIGHT[size]} ${className}`}
      role="progressbar"
      aria-valuenow={indeterminate ? undefined : Math.round(pct)}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label={label ?? "Progression"}
    >
      <div
        className={`progress-fill ${FILL[tone]}`}
        style={{ width: `${pct}%` }}
        data-static={!animated || pct >= 100 ? "true" : "false"}
      >
        {striped && <span className="absolute inset-0 bg-stripes animate-stripes" aria-hidden="true" />}
      </div>
      {indeterminate && (
        <div className={`progress-indeterminate ${FILL[tone]} opacity-70`} aria-hidden="true" />
      )}
    </div>
  );
}

export default memo(ProgressBar);
