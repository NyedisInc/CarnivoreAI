import type { OutboxEntry } from './outbox-model';

export function exportJson(entries: readonly OutboxEntry[]): string {
  return JSON.stringify(entries, null, 2);
}

function stamp(ms: number): string {
  const d = new Date(ms);
  const p = (n: number): string => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

export function exportText(entries: readonly OutboxEntry[]): string {
  return entries.map((e) => `${stamp(e.created_at)}  ${e.kind}  ${e.label.where}\n${e.label.text}\n`).join('\n');
}

export function exportFileName(ms: number): string {
  return `carnivore-outbox-${stamp(ms).replace(/[-:]/g, '').replace(' ', '-')}.json`;
}

export function download(entries: readonly OutboxEntry[], nowMs: number = Date.now()): void {
  const url = URL.createObjectURL(new Blob([exportJson(entries)], { type: 'application/json' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = exportFileName(nowMs);
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export async function copyText(text: string): Promise<boolean> {
  try {
    if (!globalThis.navigator?.clipboard?.writeText) return false;
    await globalThis.navigator.clipboard.writeText(text);
    return true;
  } catch (error) {
    console.warn('outbox: the clipboard refused', error);
    return false;
  }
}
