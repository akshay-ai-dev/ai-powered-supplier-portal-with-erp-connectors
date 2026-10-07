"use client";

import { useEffect, useRef } from "react";
import { Plus, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

export function RequirementNumberFields({ id, label, entryLabel, values, onChange, disabled }: {
  id: string;
  label: string;
  entryLabel: string;
  values: string[];
  onChange: (values: string[]) => void;
  disabled: boolean;
}) {
  const container = useRef<HTMLDivElement>(null);
  const focusNewEntry = useRef(false);

  useEffect(() => {
    if (focusNewEntry.current) {
      const inputs = container.current?.querySelectorAll("input");
      inputs?.[inputs.length - 1]?.focus();
      focusNewEntry.current = false;
    }
  }, [values.length]);

  return (
    <div ref={container} className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <Label htmlFor={`${id}-0`}>{label}</Label>
        <Button type="button" variant="outline" size="icon" disabled={disabled} aria-label={`Add ${entryLabel.toLowerCase()}`} title={`Add ${entryLabel.toLowerCase()}`}
          onClick={() => { focusNewEntry.current = true; onChange([...values, ""]); }}>
          <Plus className="size-4" />
        </Button>
      </div>
      {values.map((value, index) => (
        <div key={index} className="flex items-center gap-2">
          <Input id={`${id}-${index}`} aria-label={`${entryLabel} ${index + 1}`} value={value} maxLength={200} required disabled={disabled}
            placeholder={`Enter ${entryLabel.toLowerCase()}`}
            onChange={(event) => onChange(values.map((current, i) => i === index ? event.target.value : current))} />
          {values.length > 1 && (
            <Button type="button" variant="ghost" size="icon" disabled={disabled} aria-label={`Remove ${entryLabel.toLowerCase()} ${index + 1}`}
              onClick={() => onChange(values.filter((_, i) => i !== index))}>
              <X className="size-4" />
            </Button>
          )}
        </div>
      ))}
    </div>
  );
}
