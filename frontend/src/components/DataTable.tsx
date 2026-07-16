import { memo, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import type { DataPage } from "../types/api";

interface Props {
  data: DataPage;
  fraudColIndex?: number;
  onPageChange: (page: number) => void;
  loading?: boolean;
}

function DataTable({ data, fraudColIndex, onPageChange, loading = false }: Props) {
  const { columns, rows, page, total_pages, total, page_size } = data;

  const fraudIdx = fraudColIndex ?? columns.findIndex(
    (c) => c.toLowerCase() === "isfraud" || c.toLowerCase() === "is_fraud"
  );

  return (
    <div className="card p-0 overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-border">
        <p className="text-xs text-text-muted font-mono">
          {total.toLocaleString("fr-FR")} lignes · page {page}/{total_pages}
        </p>
        <div className="flex items-center gap-2">
          <button
            className="btn-ghost p-1.5 rounded"
            onClick={() => onPageChange(page - 1)}
            disabled={page <= 1 || loading}
            aria-label="Page précédente"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>
          <span className="text-xs text-text-dim font-mono w-16 text-center">
            {page} / {total_pages}
          </span>
          <button
            className="btn-ghost p-1.5 rounded"
            onClick={() => onPageChange(page + 1)}
            disabled={page >= total_pages || loading}
            aria-label="Page suivante"
          >
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Table */}
      <div className="overflow-x-auto">
        <table
          className="w-full text-xs font-mono min-w-max"
          aria-label="Données tabulaires"
          aria-busy={loading}
        >
          <thead>
            <tr>
              {columns.map((col) => (
                <th key={col} className="table-th whitespace-nowrap">{col}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, ri) => {
              const isFraud = fraudIdx >= 0 && Boolean(row[fraudIdx]);
              return (
                <tr
                  key={ri}
                  className={[
                    "transition-colors duration-100",
                    isFraud
                      ? "bg-accent-fraud/5 hover:bg-accent-fraud/10"
                      : "hover:bg-bg-hover",
                  ].join(" ")}
                >
                  {row.map((cell, ci) => (
                    <td
                      key={ci}
                      className={[
                        "table-td whitespace-nowrap",
                        isFraud && ci === fraudIdx ? "text-accent-fraud font-medium" : "",
                      ].join(" ")}
                    >
                      {cell === null || cell === undefined
                        ? <span className="text-text-dim">—</span>
                        : typeof cell === "number"
                          ? cell.toLocaleString("fr-FR")
                          : String(cell)}
                    </td>
                  ))}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Footer */}
      <div className="px-4 py-2 border-t border-border text-2xs text-text-dim font-mono">
        Affichage de {Math.min((page - 1) * page_size + 1, total)}–
        {Math.min(page * page_size, total)} sur {total.toLocaleString("fr-FR")} lignes
      </div>
    </div>
  );
}

export default memo(DataTable);
