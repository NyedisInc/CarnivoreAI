import type { RoundWire } from './board-model';

/* the server did not answer */
export interface Confirm { title: string; item: number; delivered: boolean; telling?: boolean; kept?: boolean; live?: 'told' | 'posted' | 'undelivered' }

export function confirmKey(confirm: Confirm): string {
  if (confirm.kept) return 'cplug.reviewboard.tray.kept';
  if (confirm.live === 'told') return 'cplug.reviewboard.tray.told';
  if (confirm.live === 'posted') return 'cplug.reviewboard.tray.told_task';
  if (!confirm.delivered) return 'cplug.reviewboard.tray.not_delivered_to';
  return confirm.telling ? 'cplug.reviewboard.tray.posted_telling' : 'cplug.reviewboard.tray.posted';
}

export function roundText(body: RoundWire): string {
  const lines: string[] = [];
  if (body.note.trim()) lines.push(body.note.trim());
  for (const a of body.answers) {
    const said = [a.options?.length ? a.options.join(', ') : '', typeof a.checked === 'boolean' ? (a.checked ? 'checked' : 'unchecked') : '', a.text ?? '', a.note].filter(Boolean).join(' / ');
    if (said) lines.push(`${a.prompt}: ${said}`);
  }
  for (const n of body.anchor_notes) lines.push(`${n.anchor}: ${n.text}`);
  if (body.payload) lines.push(`state: ${JSON.stringify(body.payload)}`);
  return lines.join('\n');
}
