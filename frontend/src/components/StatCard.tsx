interface Props {
  label: string;
  value: string | number;
  unit?: string;
  color?: "blue" | "green" | "red" | "amber" | "default";
}

const colorMap: Record<string, string> = {
  blue: "text-accent-blue",
  green: "text-accent-green",
  red: "text-accent-fraud",
  amber: "text-accent-amber",
  default: "text-text-primary",
};

export default function StatCard({ label, value, unit, color = "default" }: Props) {
  return (
    <div className="card flex flex-col justify-between min-h-[90px]">
      <p className="stat-label">{label}</p>
      <div className="flex items-baseline gap-1 mt-auto">
        <span className={`stat-value ${colorMap[color]}`}>{value}</span>
        {unit && <span className="text-xs text-text-dim">{unit}</span>}
      </div>
    </div>
  );
}
