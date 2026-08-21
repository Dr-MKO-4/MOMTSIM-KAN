import { memo } from "react";
import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  SlidersHorizontal,
  Play,
  Layers,
  Network,
  BarChart3,
  History,
  Database,
  X,
} from "lucide-react";

interface NavItem {
  label: string;
  to: string;
  icon: typeof LayoutDashboard;
  badge?: string;
  end?: boolean;
}

const NAV: NavItem[] = [
  { label: "Tableau de bord", to: "/",           icon: LayoutDashboard,  end: true },
  { label: "Configuration",   to: "/config",      icon: SlidersHorizontal },
  { label: "Calibration",     to: "/calibration", icon: BarChart3 },
  { label: "Simulation",      to: "/simulation",  icon: Play },
  { label: "Features",        to: "/features",    icon: Layers, badge: "12" },
  { label: "Dataset",         to: "/data",        icon: Database },
  { label: "Validation KAN",  to: "/kan",         icon: Network },
  { label: "Historique",      to: "/history",     icon: History },
];

interface Props {
  open: boolean;
  onClose: () => void;
}

function Sidebar({ open, onClose }: Props) {
  return (
    <aside
      className={[
        "fixed lg:static inset-y-0 left-0 z-30",
        "w-56 flex-shrink-0 flex flex-col",
        "bg-white border-r border-border h-screen",
        "transition-transform duration-200 ease-out",
        open ? "translate-x-0" : "-translate-x-full lg:translate-x-0",
      ].join(" ")}
      aria-label="Navigation principale"
    >
      {/* Logo */}
      <div className="px-5 py-4 border-b border-border flex items-start justify-between">
        <div>
          <p className="text-accent-blue font-mono text-sm font-bold tracking-widest uppercase leading-none">
            MoMTSim
          </p>
          <p className="text-text-dim text-2xs mt-1.5 font-mono tracking-wide">KAN · CEMAC · Fraude</p>
        </div>
        <button
          className="lg:hidden p-1 text-text-dim hover:text-text-primary hover:bg-bg-hover transition-colors duration-150"
          onClick={onClose}
          aria-label="Fermer le menu"
        >
          <X className="w-4 h-4" aria-hidden="true" />
        </button>
      </div>

      {/* Nav */}
      <nav className="flex-1 py-2 overflow-y-auto" aria-label="Menu principal">
        <p className="text-2xs text-text-dim uppercase tracking-widest px-5 py-2 font-semibold select-none">
          Pipeline
        </p>
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            onClick={onClose}
            className={({ isActive }) =>
              [
                "flex items-center gap-3 px-5 py-2.5 text-sm transition-colors duration-100",
                "border-l-2",
                isActive
                  ? "border-l-accent-blue bg-blue-50 text-accent-blue font-medium"
                  : "border-l-transparent text-text-muted hover:text-text-primary hover:bg-bg-hover",
              ].join(" ")
            }
          >
            {({ isActive }) => (
              <>
                <item.icon
                  className={`w-4 h-4 flex-shrink-0 ${
                    isActive ? "text-accent-blue" : "text-text-dim"
                  }`}
                  aria-hidden="true"
                />
                <span className="flex-1 leading-none">{item.label}</span>
                {item.badge && (
                  <span className="badge-blue" aria-label={`${item.badge} features`}>
                    {item.badge}
                  </span>
                )}
              </>
            )}
          </NavLink>
        ))}
      </nav>

      {/* Footer */}
      <div className="px-5 py-3 border-t border-border">
        <p className="text-2xs text-text-dim font-mono">Mémoire M2  2026</p>
        <p className="text-2xs text-text-dim mt-0.5">Chapitres 3 &amp; 4</p>
      </div>
    </aside>
  );
}

export default memo(Sidebar);
