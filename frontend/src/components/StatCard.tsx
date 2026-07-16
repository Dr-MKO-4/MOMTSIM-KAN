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

const ICON_COLOR_MAP: Record<string, string> = {
  blue:    "text-accent-blue/60",
  green:   "text-accent-green/60",
  red:     "text-accent-fraud/60",
  amber:   "text-accent-amber/60",
  default: "text-text-dim",
};

function StatCard({ label, value, unit, color = "default", icon: Icon, description }: Props) {
  return (
    <div className="card flex flex-col min-h-[96px] gap-3">
      <div className="flex items-start justify-between">
        <p className="metric-label">{label}</p>
        {Icon && (
          <Icon
            className={`w-4 h-4 flex-shrink-0 ${ICON_COLOR_MAP[color]}`}
            aria-hidden="true"
          />
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
