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
  { label: "Simulation",      to: "/simulation",  icon: Play },
  { label: "Features",        to: "/features",    icon: Layers, badge: "12" },
  { label: "Validation KAN",  to: "/kan",         icon: Network },
  { label: "Calibration",     to: "/calibration", icon: BarChart3 },
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
        "bg-bg-secondary border-r border-border h-screen",
        "transition-transform duration-200 ease-out",
        open ? "translate-x-0" : "-translate-x-full lg:translate-x-0",
      ].join(" ")}
      aria-label="Navigation principale"
    >
      {/* Logo */}
      <div className="px-5 py-4 border-b border-border flex items-start justify-between">
        <div>
          <p className="text-accent-blue font-mono text-sm font-semibold tracking-widest uppercase leading-none">
            MoMTSim
          </p>
          <p className="text-text-dim text-2xs mt-1.5 font-mono">KAN · CEMAC · Fraude</p>
        </div>
        <button
          className="lg:hidden p-1.5 rounded-lg text-text-dim hover:text-text-primary hover:bg-bg-hover transition-colors duration-150"
          onClick={onClose}
          aria-label="Fermer le menu"
        >
          <X className="w-4 h-4" aria-hidden="true" />
        </button>
      </div>

      {/* Nav */}
      <nav className="flex-1 py-3 px-2 overflow-y-auto" aria-label="Menu principal">
        <p className="text-2xs text-text-dim uppercase tracking-widest px-3 mb-2 mt-1 font-medium select-none">
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
                "flex items-center gap-3 px-3 py-2 rounded-lg text-sm mb-0.5",
                "transition-colors duration-150 cursor-pointer border",
                isActive
                  ? "bg-accent-blue/10 text-accent-blue font-medium border-accent-blue/20"
                  : "text-text-muted hover:text-text-primary hover:bg-bg-hover border-transparent",
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
        <p className="text-2xs text-text-dim font-mono">Mémoire M2 — 2025</p>
        <p className="text-2xs text-text-dim mt-0.5">Chapitres 3 &amp; 4</p>
      </div>
    </aside>
  );
}

export default memo(Sidebar);
