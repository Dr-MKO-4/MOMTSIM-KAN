import { memo, useState } from "react";
import { Check, Copy, Terminal } from "lucide-react";

interface Props {
  command: string;
  comment?: string;
}

function CommandBlock({ command, comment }: Props) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard?.writeText(command).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }).catch(() => {});
  };
  return (
    <div className="group flex items-start gap-2 rounded-xl bg-slate-900 px-3 py-2.5 text-slate-100">
      <Terminal className="w-3.5 h-3.5 mt-0.5 flex-shrink-0 text-indigo-300" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        {comment && <p className="text-2xs text-slate-400 mb-0.5">{comment}</p>}
        <code className="block text-xs font-mono break-all leading-relaxed">{command}</code>
      </div>
      <button
        className="flex-shrink-0 rounded-md p-1 text-slate-400 hover:text-white hover:bg-white/10 transition-colors"
        onClick={copy}
        title="Copier"
        aria-label="Copier la commande"
      >
        {copied ? <Check className="w-3.5 h-3.5 text-emerald-400" /> : <Copy className="w-3.5 h-3.5" />}
      </button>
    </div>
  );
}

export default memo(CommandBlock);
