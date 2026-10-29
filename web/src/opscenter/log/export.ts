import type { LogRecord } from './types';

export function recordLine(record: LogRecord): string {
  const pairs = Object.entries(record.fields).map(([k, v]) => `${k}=${v}`);
  const head = [record.approx_time && record.timestamp ? `~${record.timestamp}` : record.timestamp, record.level, record.source, record.event, ...pairs].filter(Boolean).join(' ');
  return [head, ...record.lines].join('\n');
}

export function toJsonl(records: readonly LogRecord[]): string {
  return records.map((r) => JSON.stringify(r)).join('\n') + (records.length ? '\n' : '');
}

export function exportName(now: Date): string {
  const stamp = now.toISOString().replace(/[-:]/g, '').replace('T', '-').slice(0, 15);
  return `carnivore-server-log-${stamp}.jsonl`;
}

export function downloadJsonl(records: readonly LogRecord[]): void {
  const url = URL.createObjectURL(new Blob([toJsonl(records)], { type: 'application/x-ndjson' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = exportName(new Date());
  link.click();
  URL.revokeObjectURL(url);
}

export async function copyText(text: string): Promise<boolean> {
  try {
    await globalThis.navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}
