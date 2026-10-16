import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";

interface Props {
  icon: LucideIcon;
  title: string;
  description?: string;
  children?: ReactNode;
}

export default function EmptyState({ icon: Icon, title, description, children }: Props) {
  return (
    <div className="card flex flex-col items-center justify-center text-center py-16 gap-3 animate-fade-in border-dashed">
      <span className="flex h-14 w-14 items-center justify-center rounded-2xl bg-indigo-50 text-accent-blue">
        <Icon className="w-6 h-6" aria-hidden="true" />
      </span>
      <p className="text-sm text-text-primary font-semibold">{title}</p>
      {description && (
        <p className="text-xs text-text-muted max-w-sm leading-relaxed">{description}</p>
      )}
      {children && <div className="mt-2 w-full max-w-md text-left">{children}</div>}
    </div>
  );
}
