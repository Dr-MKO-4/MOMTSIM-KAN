import { useId } from "react";

interface Props {
  label: string;
  value: number;
  onChange: (name: string, value: number) => void;
  name: string;
  min?: number;
  max?: number;
  step?: number;
  isFloat?: boolean;
  hint?: string;
}

export default function FormField({
  label, value, onChange, name, min, max, step = 1, isFloat = false, hint,
}: Props) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="label">{label}</label>
      <input
        id={id}
        type="number"
        className="input"
        value={value}
        min={min}
        max={max}
        step={isFloat ? 0.001 : step}
        onChange={(e) => { const v = parseFloat(e.target.value); if (!isNaN(v)) onChange(name, v); }}
        aria-describedby={hint ? `${id}-hint` : undefined}
      />
      {hint && (
        <p id={`${id}-hint`} className="text-2xs text-text-dim mt-1">{hint}</p>
      )}
    </div>
  );
}
