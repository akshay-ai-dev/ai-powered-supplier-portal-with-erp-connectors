"use client";

import { useState } from "react";
import { Download, FileText, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { downloadRequirementPreview, type PreviewField, type PreviewFormat } from "@/lib/requirement-export";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function RequirementPreview({ fields, disabled }: { fields: PreviewField[]; disabled: boolean }) {
  const [exporting, setExporting] = useState<PreviewFormat | null>(null);
  async function download(format: PreviewFormat) {
    setExporting(format);
    try { await downloadRequirementPreview(fields, format); }
    catch (err) { toast.error(err instanceof Error ? err.message : "Could not download the preview."); }
    finally { setExporting(null); }
  }

  return (
    <Card className="h-fit min-w-0">
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><FileText className="size-4" />Requirement preview</CardTitle>
        <p className="text-xs text-muted-foreground">Draft · Updates as you fill out the form.</p>
        <div className="flex flex-wrap gap-2 pt-2">
          {(["pdf", "docx", "txt"] as const).map((format) => (
            <Button key={format} type="button" variant="outline" size="sm" disabled={disabled || !!exporting} onClick={() => download(format)}>
              {exporting === format ? <Loader2 className="size-4 animate-spin" /> : <Download className="size-4" />}
              Download {format.toUpperCase()}
            </Button>
          ))}
        </div>
      </CardHeader>
      <CardContent>
        <dl className="space-y-3 text-sm">
          {fields.map(({ label, value }) => <div key={label}><dt className="text-xs font-medium text-muted-foreground">{label}</dt><dd className="mt-1 whitespace-pre-wrap break-words">{value}</dd></div>)}
        </dl>
      </CardContent>
    </Card>
  );
}
