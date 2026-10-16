import { memo } from "react";
import type { LucideIcon } from "lucide-react";

interface Props {
  label: string;
  value: string | number;
  unit?: string;
  color?: "blue" | "green" | "red" | "amber" | "default";
  icon?: LucideIcon;
  description?: string;
}

const COLOR_MAP: Record<string, string> = {
  blue:    "text-accent-blue",
  green:   "text-accent-green",
  red:     "text-accent-fraud",
  amber:   "text-accent-amber",
  default: "text-text-primary",
};

const BUBBLE_MAP: Record<string, string> = {
  blue:    "bg-indigo-50 text-accent-blue",
  green:   "bg-emerald-50 text-accent-green",
  red:     "bg-rose-50 text-accent-fraud",
  amber:   "bg-amber-50 text-accent-amber",
  default: "bg-slate-100 text-text-muted",
};

function StatCard({ label, value, unit, color = "default", icon: Icon, description }: Props) {
  return (
    <div className="card flex flex-col min-h-[104px] gap-3 transition-shadow duration-200 hover:shadow-soft">
      <div className="flex items-start justify-between gap-2">
        <p className="metric-label">{label}</p>
        {Icon && (
          <span className={`flex h-8 w-8 items-center justify-center rounded-xl ${BUBBLE_MAP[color]}`}>
            <Icon className="w-4 h-4" aria-hidden="true" />
          </span>
        )}
      </div>
      <div className="flex items-baseline gap-1.5 mt-auto">
        <span className={`metric-value ${COLOR_MAP[color]}`}>{value}</span>
        {unit && <span className="text-xs text-text-dim">{unit}</span>}
      </div>
      {description && (
        <p className="text-2xs text-text-dim leading-relaxed -mt-1">{description}</p>
      )}
    </div>
  );
}

export default memo(StatCard);
