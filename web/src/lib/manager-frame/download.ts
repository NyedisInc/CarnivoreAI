
export function downloadJson(filename: string, document: unknown, doc: Document = globalThis.document): string {
    return downloadBlob(filename, new Blob([`${JSON.stringify(document, null, 2)}\n`], { type: 'application/json' }), doc);
}

export function downloadBlob(filename: string, blob: Blob, doc: Document = globalThis.document): string {
    const url = URL.createObjectURL(blob);
    const link = doc.createElement('a');
    link.href = url;
    link.download = filename;
    link.rel = 'noopener';
    doc.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 0);
    return filename;
}
