import { memo } from "react";
import { BarChart2 } from "lucide-react";

interface Props {
  html: string;
  title?: string;
  height?: number;
}

const IFRAME_BASE = `<!doctype html><html><head>
  <meta charset="utf-8"/>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    html, body { width: 100%; height: 100%; background: #0D0F18; overflow: hidden; }
    .plotly-graph-div { width: 100% !important; height: 100% !important; }
  </style>
</head><body>`;

function PlotlyEmbed({ html, title, height = 480 }: Props) {
  const srcdoc = `${IFRAME_BASE}${html}</body></html>`;

  return (
    <div className="card p-0 overflow-hidden">
      {title && (
        <div className="flex items-center gap-2 px-4 py-2.5 border-b border-border">
          <BarChart2 className="w-3.5 h-3.5 text-text-dim flex-shrink-0" aria-hidden="true" />
          <p className="text-xs font-mono text-text-muted">{title}</p>
        </div>
      )}
      <iframe
        srcDoc={srcdoc}
        style={{ width: "100%", height, border: "none", display: "block" }}
        sandbox="allow-scripts"
        title={title ?? "Graphique Plotly"}
        loading="lazy"
      />
    </div>
  );
}

export default memo(PlotlyEmbed);
