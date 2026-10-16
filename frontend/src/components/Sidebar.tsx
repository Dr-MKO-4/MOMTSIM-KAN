import { memo } from "react";
import { NavLink } from "react-router-dom";
import {
  LayoutDashboard,
  SlidersHorizontal,
  Play,
  Layers,
  Network,
  Target,
  History,
  Database,
  X,
  Sparkles,
} from "lucide-react";

interface NavItem {
  label: string;
  to: string;
  icon: typeof LayoutDashboard;
  badge?: string;
  end?: boolean;
}

const GROUPS: { title: string; items: NavItem[] }[] = [
  { title: "Vue d'ensemble", items: [
    { label: "Tableau de bord", to: "/", icon: LayoutDashboard, end: true },
  ]},
  { title: "Préparation", items: [
    { label: "Scénarios",   to: "/config",      icon: SlidersHorizontal },
    { label: "Calibration", to: "/calibration", icon: Target },
  ]},
  { title: "Génération", items: [
    { label: "Simulation", to: "/simulation", icon: Play },
    { label: "Features",   to: "/features",   icon: Layers, badge: "12" },
    { label: "Données",    to: "/data",       icon: Database },
  ]},
  { title: "Analyse", items: [
    { label: "Validation KAN", to: "/kan",     icon: Network },
    { label: "Historique",     to: "/history", icon: History },
  ]},
];

interface Props {
  open: boolean;
  onClose: () => void;
}

function Sidebar({ open, onClose }: Props) {
  return (
    <aside
      className={[
        "fixed lg:sticky top-0 inset-y-0 left-0 z-30",
        "w-64 flex-shrink-0 flex flex-col h-screen",
        "bg-white/90 backdrop-blur border-r border-border",
        "transition-transform duration-200 ease-out",
        open ? "translate-x-0" : "-translate-x-full lg:translate-x-0",
      ].join(" ")}
      aria-label="Navigation principale"
    >
      {/* Marque */}
      <div className="px-5 pt-5 pb-4 flex items-start justify-between">
        <div className="flex items-center gap-3">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-gradient text-white shadow-soft">
            <Sparkles className="w-4 h-4" aria-hidden="true" />
          </span>
          <div>
            <p className="text-sm font-semibold text-text-primary leading-none tracking-tight">MoMTSim</p>
            <p className="text-2xs text-text-dim mt-1">Fraude Mobile Money · CEMAC</p>
          </div>
        </div>
        <button className="lg:hidden btn-icon" onClick={onClose} aria-label="Fermer le menu">
          <X className="w-4 h-4" aria-hidden="true" />
        </button>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 pb-3 overflow-y-auto space-y-4" aria-label="Menu principal">
        {GROUPS.map((g) => (
          <div key={g.title}>
            <p className="px-3 pb-1.5 text-2xs font-semibold uppercase tracking-wider text-text-dim select-none">
              {g.title}
            </p>
            <div className="space-y-0.5">
              {g.items.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.end}
                  onClick={onClose}
                  className={({ isActive }) =>
                    [
                      "group flex items-center gap-3 px-3 py-2 rounded-xl text-sm transition-all duration-150",
                      isActive
                        ? "bg-indigo-50 text-accent-blue font-medium shadow-[inset_0_0_0_1px_rgb(199_210_254)]"
                        : "text-text-muted hover:text-text-primary hover:bg-bg-hover",
                    ].join(" ")
                  }
                >
                  {({ isActive }) => (
                    <>
                      <span className={`flex h-7 w-7 items-center justify-center rounded-lg transition-colors ${
                        isActive ? "bg-white text-accent-blue shadow-card" : "text-text-dim group-hover:text-text-muted"}`}>
                        <item.icon className="w-4 h-4" aria-hidden="true" />
                      </span>
                      <span className="flex-1 leading-none">{item.label}</span>
                      {item.badge && <span className="badge-blue">{item.badge}</span>}
                    </>
                  )}
                </NavLink>
              ))}
            </div>
          </div>
        ))}
      </nav>

      {/* Pied */}
      <div className="m-3 rounded-xl bg-bg-sunken/70 px-4 py-3">
        <p className="text-2xs font-medium text-text-muted">Mémoire M2 · 2026</p>
        <p className="text-2xs text-text-dim mt-0.5">Simulation multi-agents, chapitre 3</p>
      </div>
    </aside>
  );
}

export default memo(Sidebar);
