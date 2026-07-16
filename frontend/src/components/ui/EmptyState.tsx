import type { LucideIcon } from "lucide-react";

interface Props {
  icon: LucideIcon;
  title: string;
  description?: string;
}

export default function EmptyState({ icon: Icon, title, description }: Props) {
  return (
    <div className="card flex flex-col items-center justify-center text-center py-14 gap-3 animate-fade-in">
      <Icon className="w-9 h-9 text-text-dim" aria-hidden="true" />
      <p className="text-sm text-text-muted font-medium">{title}</p>
      {description && (
        <p className="text-xs text-text-dim max-w-xs leading-relaxed">{description}</p>
      )}
    </div>
  );
}
