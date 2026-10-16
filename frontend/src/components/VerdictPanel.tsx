import { memo } from "react";
import { ShieldCheck, ShieldAlert, RefreshCcw, AlertTriangle, Info, CheckCircle2, ArrowRight } from "lucide-react";
import type { Verdict, CheckLevel } from "../types/api";
import CommandBlock from "./ui/CommandBlock";

const VERDICT_STYLE: Record<string, { title: string; icon: typeof ShieldCheck; cls: string; ring: string }> = {
  OK:          { title: "Pas besoin de relancer", icon: ShieldCheck, cls: "from-emerald-500 to-teal-500", ring: "ring-emerald-200" },
  ACCEPTABLE:  { title: "Utilisable, avec réserves", icon: ShieldAlert, cls: "from-amber-500 to-orange-500", ring: "ring-amber-200" },
  RELANCER:    { title: "À relancer", icon: RefreshCcw, cls: "from-rose-600 to-pink-500", ring: "ring-rose-200" },
  "A REFAIRE": { title: "Jeu à régénérer", icon: RefreshCcw, cls: "from-rose-600 to-pink-500", ring: "ring-rose-200" },
};

const LEVEL: Record<CheckLevel, { icon: typeof Info; cls: string; label: string }> = {
  bloquant:  { icon: AlertTriangle, cls: "text-accent-fraud bg-rose-50",     label: "Bloquant" },
  attention: { icon: AlertTriangle, cls: "text-accent-amber bg-amber-50",    label: "Attention" },
  info:      { icon: Info,          cls: "text-accent-blue bg-indigo-50",    label: "Info" },
  ok:        { icon: CheckCircle2,  cls: "text-accent-green bg-emerald-50",  label: "OK" },
};

const ORDER: CheckLevel[] = ["bloquant", "attention", "ok", "info"];

interface Props {
  verdict: Verdict;
  title?: string;
  commands?: string[];
}

function VerdictPanel({ verdict, title, commands }: Props) {
  const st = VERDICT_STYLE[verdict.verdict] ?? VERDICT_STYLE.ACCEPTABLE;
  const Icon = st.icon;
  const checks = [...verdict.checks].sort((a, b) => ORDER.indexOf(a.level) - ORDER.indexOf(b.level));
  const cmds = commands ?? verdict.next_steps ?? [];

  return (
    <div className={`card p-0 overflow-hidden ring-1 ${st.ring}`}>
      <div className={`bg-gradient-to-r ${st.cls} px-5 py-4 text-white flex items-center gap-3`}>
        <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-white/20">
          <Icon className="w-5 h-5" aria-hidden="true" />
        </span>
        <div className="min-w-0">
          <p className="text-2xs uppercase tracking-wider opacity-80">{title ?? "Verdict"}</p>
          <p className="text-base font-semibold leading-tight">{verdict.verdict} · {st.title}</p>
        </div>
      </div>
      <div className="p-5 space-y-3">
        {verdict.summary && <p className="text-sm text-text-muted leading-relaxed">{verdict.summary}</p>}
        <ul className="space-y-2">
          {checks.map((c, i) => {
            const L = LEVEL[c.level] ?? LEVEL.info;
            const LI = L.icon;
            return (
              <li key={i} className="flex gap-3 rounded-xl border border-border-subtle p-3">
                <span className={`flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-lg ${L.cls}`}>
                  <LI className="w-3.5 h-3.5" aria-hidden="true" />
                </span>
                <div className="min-w-0 space-y-1">
                  <p className="text-xs font-semibold text-text-primary">
                    {c.title} <span className="ml-1 text-2xs font-normal text-text-dim">{L.label}</span>
                  </p>
                  <p className="text-xs text-text-muted leading-relaxed">{c.detail}</p>
                  {c.action && (
                    <p className="text-xs text-accent-blue leading-relaxed flex gap-1.5">
                      <ArrowRight className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" aria-hidden="true" />
                      <span>{c.action}</span>
                    </p>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
        {cmds.length > 0 && (
          <div className="pt-1 space-y-2">
            <p className="metric-label">Commandes (dossier MOMTSIM)</p>
            {cmds.map((c) => <CommandBlock key={c} command={c} />)}
          </div>
        )}
      </div>
    </div>
  );
}

export default memo(VerdictPanel);
