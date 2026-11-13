import type { ReactNode } from "react";
import "./bulk-edit-field.css";

export function BulkEditField({
  label,
  enabled,
  onToggle,
  children,
}: {
  label: string;
  enabled: boolean;
  onToggle: (enabled: boolean) => void;
  children: ReactNode;
}) {
  return (
    <div className="bulk-edit-field">
      <label className="bulk-edit-toggle">
        <input
          type="checkbox"
          aria-label={`${label} değiştir`}
          checked={enabled}
          onChange={(event) => onToggle(event.target.checked)}
        />
        <span>{label}</span>
      </label>
      {children}
    </div>
  );
}
