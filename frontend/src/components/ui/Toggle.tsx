import { useId } from "react";

interface Props {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  hint?: string;
}

export default function Toggle({ label, checked, onChange, hint }: Props) {
  const id = useId();
  return (
    <div className="flex items-start justify-between gap-3">
      <div className="min-w-0">
        <label htmlFor={id} className="text-xs font-medium text-text-primary cursor-pointer">{label}</label>
        {hint && <p className="text-2xs text-text-dim mt-0.5 leading-relaxed">{hint}</p>}
      </div>
      <button
        id={id}
        type="button"
        role="switch"
        aria-checked={checked}
        className="toggle mt-0.5"
        data-on={checked ? "true" : "false"}
        onClick={() => onChange(!checked)}
      >
        <span className="toggle-knob" />
      </button>
    </div>
  );
}
