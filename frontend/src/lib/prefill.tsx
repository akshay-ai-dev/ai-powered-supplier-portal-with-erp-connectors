"use client";
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";

/** Values the assistant collected for a form. Keys are the same names the form's own API body uses. */
export interface Prefill {
  form: string;
  target: number | null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  values: Record<string, any>;
}

interface Ctx {
  prefill: Prefill | null;
  setPrefill: (p: Prefill | null) => void;
}
const PrefillCtx = createContext<Ctx>({ prefill: null, setPrefill: () => {} });

const EXPIRES_MS = 60_000;

/** Carries assistant values from the chat to the form page. They expire if no form picks them up. */
export function PrefillProvider({ children }: { children: React.ReactNode }) {
  const [prefill, setState] = useState<Prefill | null>(null);
  const timer = useRef<number | undefined>(undefined);
  const setPrefill = useCallback((p: Prefill | null) => {
    window.clearTimeout(timer.current);
    setState(p);
    if (p) timer.current = window.setTimeout(() => setState(null), EXPIRES_MS);
  }, []);
  return <PrefillCtx.Provider value={{ prefill, setPrefill }}>{children}</PrefillCtx.Provider>;
}

export const usePrefill = () => useContext(PrefillCtx);

const AI_RING = "ring-2 ring-violet-400/70";

/**
 * Called by a form. When the assistant has values for this form (and this record, for forms that live on a
 * requirement or order page) they are applied once through `apply`, and the fields are marked as AI-filled.
 * The form still needs the user's own Save.
 */
export function useAiFill(form: string, apply: (values: Prefill["values"]) => void, target?: number | string, ready = true) {
  const { prefill, setPrefill } = usePrefill();
  const [fields, setFields] = useState<string[]>([]);
  const latest = useRef(apply);
  latest.current = apply;

  useEffect(() => {
    if (!ready || !prefill || prefill.form !== form) return;
    if (target !== undefined && String(prefill.target) !== String(target)) return;
    latest.current(prefill.values);
    setFields(Object.keys(prefill.values));
    setPrefill(null);
  }, [prefill, form, target, ready, setPrefill]);

  return {
    any: fields.length > 0,
    /** Tailwind classes that mark a field as filled by the assistant (empty string otherwise). */
    ring: (key: string) => (fields.includes(key) ? AI_RING : ""),
    clear: () => setFields([]),
  };
}

export function AiBanner({ show, onDismiss }: { show: boolean; onDismiss: () => void }) {
  if (!show) return null;
  return (
    <div className="mb-4 flex items-start justify-between gap-3 rounded-md border border-violet-400/50 bg-violet-500/10 px-3 py-2 text-sm">
      <span>
        <b>Filled by the assistant.</b> Check every field, change anything you like, then save the form yourself. Nothing has been saved yet.
      </span>
      <button type="button" className="shrink-0 text-xs underline" onClick={onDismiss}>
        Dismiss
      </button>
    </div>
  );
}
