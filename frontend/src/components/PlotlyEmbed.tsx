interface Props {
  html: string;
  title?: string;
  height?: number;
}

export default function PlotlyEmbed({ html, title, height = 480 }: Props) {
  const srcdoc = `<!doctype html><html><head>
    <meta charset="utf-8"/>
    <style>
      * { margin: 0; padding: 0; box-sizing: border-box; }
      body { background: #0F1117; }
    </style>
  </head><body>${html}</body></html>`;

  return (
    <div className="card p-0 overflow-hidden">
      {title && (
        <div className="px-4 py-2 border-b border-border">
          <p className="text-xs font-mono text-text-muted">{title}</p>
        </div>
      )}
      <iframe
        srcDoc={srcdoc}
        style={{ width: "100%", height, border: "none" }}
        sandbox="allow-scripts"
        title={title ?? "Plotly chart"}
      />
    </div>
  );
}
