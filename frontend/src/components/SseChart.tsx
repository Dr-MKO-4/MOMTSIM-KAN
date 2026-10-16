import { memo, useMemo } from "react";
import type { CalibrationHistoryEntry } from "../types/api";

interface Props {
  history: CalibrationHistoryEntry[];
  sseZero?: number | null;     // SSE d'une sortie sans fraude
  sseTheta0?: number | null;   // SSE au départ analytique
  height?: number;
}

/* Courbe SVG de la SSE par itération (valeur courante et meilleure valeur), avec
   deux références horizontales : départ analytique θ0 et sortie sans aucune fraude. */
function SseChart({ history, sseZero, sseTheta0, height = 220 }: Props) {
  const W = 640, H = height, P = { l: 56, r: 16, t: 14, b: 28 };
  const data = useMemo(() => history.filter((h) => typeof h.sse === "number"), [history]);

  const { xs, ys, best, yMin, yMax } = useMemo(() => {
    const ys = data.map((d) => d.sse);
    let b = Infinity;
    const best = data.map((d) => (b = Math.min(b, d.best_sse ?? d.sse)));
    const refs = [sseZero, sseTheta0].filter((v): v is number => typeof v === "number");
    const all = [...ys, ...refs];
    const lo = all.length ? Math.min(...all) : 0;
    const hi = all.length ? Math.max(...all) : 1;
    const pad = (hi - lo) * 0.08 || hi * 0.1 || 1;
    return { xs: data.map((d) => d.iter), ys, best, yMin: Math.max(0, lo - pad), yMax: hi + pad };
  }, [data, sseZero, sseTheta0]);

  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center rounded-xl bg-bg-sunken/60 text-xs text-text-dim" style={{ height }}>
        La courbe apparaît après la première itération évaluée.
      </div>
    );
  }

  const xMax = Math.max(1, ...xs);
  const sx = (x: number) => P.l + (x / xMax) * (W - P.l - P.r);
  const sy = (y: number) => P.t + (1 - (y - yMin) / (yMax - yMin || 1)) * (H - P.t - P.b);
  const path = (vals: number[]) => vals.map((v, i) => `${i ? "L" : "M"}${sx(xs[i]).toFixed(1)},${sy(v).toFixed(1)}`).join(" ");
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => yMin + f * (yMax - yMin));

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" role="img" aria-label="Évolution de la SSE par itération">
      <defs>
        <linearGradient id="sse-area" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stopColor="#4F46E5" stopOpacity="0.18" />
          <stop offset="100%" stopColor="#4F46E5" stopOpacity="0" />
        </linearGradient>
      </defs>
      {ticks.map((t) => (
        <g key={t}>
          <line x1={P.l} x2={W - P.r} y1={sy(t)} y2={sy(t)} stroke="#E2E6F0" strokeDasharray="3 4" />
          <text x={P.l - 8} y={sy(t) + 3} textAnchor="end" fontSize="10" fill="#94A3B8" fontFamily="JetBrains Mono, monospace">
            {t.toExponential(1)}
          </text>
        </g>
      ))}
      {typeof sseZero === "number" && (
        <g>
          <line x1={P.l} x2={W - P.r} y1={sy(sseZero)} y2={sy(sseZero)} stroke="#E11D48" strokeWidth="1.2" strokeDasharray="6 4" />
          <text x={W - P.r} y={sy(sseZero) - 4} textAnchor="end" fontSize="10" fill="#E11D48">sans fraude</text>
        </g>
      )}
      {typeof sseTheta0 === "number" && (
        <g>
          <line x1={P.l} x2={W - P.r} y1={sy(sseTheta0)} y2={sy(sseTheta0)} stroke="#D97706" strokeWidth="1.2" strokeDasharray="2 3" />
          <text x={W - P.r} y={sy(sseTheta0) - 4} textAnchor="end" fontSize="10" fill="#D97706">départ θ0</text>
        </g>
      )}
      <path d={`${path(ys)} L${sx(xs[xs.length - 1])},${H - P.b} L${sx(xs[0])},${H - P.b} Z`} fill="url(#sse-area)" />
      <path d={path(ys)} fill="none" stroke="#818CF8" strokeWidth="1.5" />
      <path d={path(best)} fill="none" stroke="#4F46E5" strokeWidth="2.4" strokeLinejoin="round" />
      {ys.map((v, i) => <circle key={i} cx={sx(xs[i])} cy={sy(v)} r="2.4" fill="#4F46E5" />)}
      {[0, xMax].map((x) => (
        <text key={x} x={sx(x)} y={H - 8} textAnchor="middle" fontSize="10" fill="#94A3B8">{`it. ${x}`}</text>
      ))}
      <g transform={`translate(${P.l + 8}, ${P.t + 6})`} fontSize="10" fill="#475569">
        <rect width="10" height="3" y="3" fill="#4F46E5" /><text x="14" y="8">meilleure SSE</text>
        <rect width="10" height="2" x="96" y="3" fill="#818CF8" /><text x="110" y="8">SSE de l'itération</text>
      </g>
    </svg>
  );
}

export default memo(SseChart);
