import { NavLink } from "react-router-dom";

interface NavItem {
  label: string;
  to: string;
  icon: string;
  badge?: string;
}

const NAV: NavItem[] = [
  { label: "Tableau de bord", to: "/", icon: "⬡" },
  { label: "Configuration", to: "/config", icon: "⚙" },
  { label: "Simulation", to: "/simulation", icon: "▶" },
  { label: "Features", to: "/features", icon: "∑", badge: "12" },
  { label: "Validation KAN", to: "/kan", icon: "κ" },
  { label: "Calibration", to: "/calibration", icon: "↺" },
];

export default function Sidebar() {
  return (
    <aside className="w-56 flex-shrink-0 flex flex-col bg-bg-secondary border-r border-border h-screen sticky top-0">
      {/* Logo */}
      <div className="px-5 py-4 border-b border-border">
        <p className="text-accent-blue font-mono text-sm font-medium tracking-widest uppercase">
          MoMTSim
        </p>
        <p className="text-text-dim text-2xs mt-0.5">KAN · CEMAC · Fraude</p>
      </div>

      {/* Nav */}
      <nav className="flex-1 py-4 space-y-0.5 px-2 overflow-y-auto">
        {NAV.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === "/"}
            className={({ isActive }) =>
              `flex items-center gap-3 px-3 py-2 rounded-lg text-sm transition-colors duration-100 cursor-pointer
               ${isActive
                 ? "bg-accent-blue/15 text-accent-blue font-medium"
                 : "text-text-muted hover:text-text-primary hover:bg-bg-card"
               }`
            }
          >
            <span className="font-mono text-base w-4 text-center flex-shrink-0">
              {item.icon}
            </span>
            <span className="flex-1">{item.label}</span>
            {item.badge && (
              <span className="badge-blue text-2xs">{item.badge}</span>
            )}
          </NavLink>
        ))}
      </nav>

      {/* Footer */}
      <div className="px-5 py-3 border-t border-border">
        <p className="text-2xs text-text-dim font-mono">Mémoire M2 · 2025</p>
        <p className="text-2xs text-text-dim">Chapitre 3–4</p>
      </div>
    </aside>
  );
}
