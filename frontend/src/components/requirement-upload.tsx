"use client";

import { useRef, useState } from "react";
import { FileText, ImageIcon, Upload, X } from "lucide-react";
import { fileSize } from "@/lib/api";
import { Button } from "@/components/ui/button";

const MAX_BYTES = 10 * 1024 * 1024;

export function RequirementUpload({ files, onChange, disabled = false }: {
  files: File[];
  onChange: (files: File[]) => void;
  disabled?: boolean;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [errors, setErrors] = useState<string[]>([]);

  function addFiles(incoming: File[]) {
    if (disabled) return;
    const invalid: string[] = [];
    const accepted = [...files];
    for (const file of incoming) {
      if (!/\.(pdf|jpe?g)$/i.test(file.name) || (file.type && !["application/pdf", "image/jpeg"].includes(file.type))) {
        invalid.push(`${file.name}: choose a PDF or JPG file.`);
      } else if (!file.size || file.size > MAX_BYTES) {
        invalid.push(`${file.name}: files must be non-empty and no larger than 10 MB.`);
      } else if (!accepted.some((existing) => existing.name === file.name && existing.size === file.size && existing.lastModified === file.lastModified)) {
        accepted.push(file);
      }
    }
    setErrors(invalid);
    onChange(accepted);
  }

  return (
    <section aria-labelledby="requirement-upload-title" className="space-y-3 rounded-lg border p-4">
      <div>
        <h2 id="requirement-upload-title" className="flex items-center gap-2 text-sm font-semibold"><Upload className="size-4 text-primary" />Upload requirement files</h2>
        <p className="mt-1 text-xs text-muted-foreground">Add PDF documents or JPG images. Files are attached when you post this requirement.</p>
      </div>
      <input ref={input} type="file" multiple accept=".pdf,.jpg,.jpeg,application/pdf,image/jpeg" aria-label="Choose PDF or JPG files" className="hidden" disabled={disabled}
        onChange={(event) => { addFiles(Array.from(event.target.files ?? [])); event.target.value = ""; }} />
      <button type="button" disabled={disabled} onClick={() => input.current?.click()}
        onDragOver={(event) => { event.preventDefault(); if (!disabled) setDragging(true); }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => { event.preventDefault(); setDragging(false); addFiles(Array.from(event.dataTransfer.files)); }}
        className={`flex min-h-36 w-full flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed p-6 text-center transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50 ${dragging ? "border-primary bg-primary/10" : "border-primary/40 bg-primary/5 hover:bg-primary/10"}`}>
        <Upload className="size-6 text-primary" />
        <span className="text-sm font-medium">Drop files here or click to browse</span>
        <span className="text-xs text-muted-foreground">PDF, JPG or JPEG · Maximum 10 MB per file</span>
      </button>
      {!!errors.length && <ul role="alert" className="space-y-1 text-sm text-destructive">{errors.map((message, index) => <li key={index}>{message}</li>)}</ul>}
      {!!files.length && (
        <ul className="divide-y rounded-md border" aria-label="Selected files">
          {files.map((file, index) => (
            <li key={`${file.name}-${file.lastModified}-${index}`} className="flex items-center gap-3 p-3 text-sm">
              {/\.pdf$/i.test(file.name) ? <FileText className="size-5 shrink-0 text-primary" /> : <ImageIcon className="size-5 shrink-0 text-primary" />}
              <div className="min-w-0 flex-1"><p className="truncate">{file.name}</p><p className="text-xs text-muted-foreground">{fileSize(file.size)}</p></div>
              <Button type="button" variant="ghost" size="icon" aria-label={`Remove ${file.name}`} disabled={disabled} onClick={() => onChange(files.filter((_, i) => i !== index))}><X className="size-4" /></Button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
