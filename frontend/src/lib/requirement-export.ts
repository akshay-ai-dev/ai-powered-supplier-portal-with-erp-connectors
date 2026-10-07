export type PreviewField = { label: string; value: string };
export type PreviewFormat = "pdf" | "docx" | "txt";

export async function createRequirementPreview(fields: PreviewField[], format: PreviewFormat): Promise<Blob> {
  if (format === "txt") {
    const text = ["Requirement preview", "Draft - Review before posting", "",
      ...fields.map(({ label, value }) => `${label}\n${value}\n`),
    ].join("\n");
    return new Blob([text], { type: "text/plain;charset=utf-8" });
  }
  if (format === "docx") {
    const { Document, Packer, Paragraph, TextRun, HeadingLevel } = await import("docx");
    const document = new Document({
      title: "Requirement preview",
      sections: [{ children: [
        new Paragraph({ text: "Requirement preview", heading: HeadingLevel.TITLE }),
        new Paragraph({ text: "Draft · Review before posting", spacing: { after: 300 } }),
        ...fields.flatMap(({ label, value }) => [
          new Paragraph({ children: [new TextRun({ text: label, bold: true })], spacing: { before: 160 } }),
          ...value.split("\n").map((text) => new Paragraph({ text })),
        ]),
      ] }],
    });
    return Packer.toBlob(document);
  }

  const { jsPDF } = await import("jspdf");
  const document = new jsPDF({ unit: "mm", format: "a4" });
  document.setProperties({ title: "Requirement preview" });
  const margin = 18;
  const bottom = document.internal.pageSize.getHeight() - margin;
  const width = document.internal.pageSize.getWidth() - margin * 2;
  let y = margin;
  const write = (text: string, size: number, bold: boolean) => {
    document.setFont("helvetica", bold ? "bold" : "normal");
    document.setFontSize(size);
    const lines: string[] = document.splitTextToSize(text, width);
    const height = size * 0.3528 * 1.35;
    for (const line of lines) {
      if (y + height > bottom) { document.addPage(); y = margin; }
      document.text(line, margin, y);
      y += height;
    }
  };
  write("Requirement preview", 20, true);
  write("Draft - Review before posting", 10, false);
  y += 6;
  for (const { label, value } of fields) {
    // Keep the field label with at least its first value line.
    if (y + 14 > bottom) { document.addPage(); y = margin; }
    write(label, 10, true);
    write(value, 11, false);
    y += 4;
  }
  return document.output("blob");
}

export async function downloadRequirementPreview(fields: PreviewField[], format: PreviewFormat) {
  const blob = await createRequirementPreview(fields, format);
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `requirement-preview.${format}`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
