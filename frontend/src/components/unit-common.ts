import type { FieldType } from "@/lib/types";

export const selectCls = "h-9 rounded-md border bg-background px-3 text-sm";
export const msg = (e: unknown) => (e instanceof Error ? e.message : "Something went wrong");

export function formatValue(f: { type: FieldType; unit_label: string }, v: string | number | undefined | null) {
  if (v == null || v === "") return "—";
  if (f.type === "pass_fail") return v === "pass" ? "Pass" : "Fail";
  return f.type === "number" && f.unit_label ? `${v} ${f.unit_label}` : String(v);
}


/** Does this typed value pass the field's rule? Mirrors the server so the dialog can warn before saving. */
export function judge(f: { type: FieldType; min_value: number | null; max_value: number | null }, raw: string): "pass" | "fail" | null {
  const text = raw.trim();
  if (!text) return null;
  if (f.type === "pass_fail") return text === "pass" ? "pass" : "fail";
  if (f.type === "number") {
    const n = Number(text.replace(",", "."));
    if (Number.isNaN(n)) return "fail";
    if ((f.min_value != null && n < f.min_value) || (f.max_value != null && n > f.max_value)) return "fail";
  }
  return "pass";
}
