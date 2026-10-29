import { t } from '../../i18n/index.svelte';
import type { RunAttachment, SchedulePreview } from '../api';
import type { DiffEntry, DiffResult } from '../logic/diff';
import { bytesWords } from '../logic/words';
import { needsYou } from '../overview/overview-model';

export const NEXT_FIRES = 3;

export interface SentenceRun {
  status: string;
  reason: string | null;
  title?: string | null;
}

export function statusSentence(i: { enabled: boolean; paused: boolean; last: SentenceRun | null; reviewed: boolean; nextText: string }): string {
  if (!i.enabled) return t('automations.simple.dr.sent_off');
  if (i.paused) return t('automations.simple.dr.sent_paused');
  if (i.last && needsYou(i.last) && !i.reviewed && i.last.title) return `${i.last.title}.`;
  return t('automations.simple.dr.sent_next', { when: i.nextText });
}

function tail(label: string): string {
  const parts = label.split(' / ');
  return (parts.length > 2 ? parts.slice(1) : parts).join(' ');
}

function first(entries: readonly DiffEntry[], pick: (e: DiffEntry) => boolean): DiffEntry | undefined {
  return entries.find(pick);
}

/* there is nothing */
export function sinceSentence(result: Pick<DiffResult, 'same' | 'entries' | 'counts'> | null): string {
  if (!result) return '';
  if (result.same) return t('automations.simple.since.same');
  const e = result.entries;
  const s = first(e, (x) => x.kind === 'string' && typeof x.old === 'string' && typeof x.new === 'string' && x.path !== 'summary');
  if (s) return t('automations.simple.since.went', { label: tail(s.label), old: String(s.old), new: String(s.new) });
  const n = first(e, (x) => x.kind === 'number');
  if (n) return t('automations.simple.since.moved', { label: tail(n.label), old: String(n.old), new: String(n.new) });
  const a = first(e, (x) => x.kind === 'appeared' || x.kind === 'cleared');
  if (a) return t(a.kind === 'appeared' ? 'automations.simple.since.new' : 'automations.simple.since.gone', { label: tail(a.label) });
  const total = result.counts.total;
  if (!total) return t('automations.simple.since.same');
  return t(total === 1 ? 'automations.simple.since.count_one' : 'automations.simple.since.count_many', { n: total });
}

export function nextFires(preview: SchedulePreview | null, rowNext: number | null): number[] {
  if (preview?.ok) {
    const out = preview.fires.map((f) => Date.parse(f.utc) / 1000).filter((x) => Number.isFinite(x));
    if (out.length) return out.slice(0, NEXT_FIRES);
  }
  return rowNext != null ? [rowNext] : [];
}

export function attachmentRows(list: readonly RunAttachment[] | null | undefined): { name: string; size: string }[] {
  return (list ?? []).map((x) => ({ name: x.name || t('automations.simple.dr.file'), size: x.bytes != null ? bytesWords(x.bytes) : '' }));
}

export function runWords(run: { title?: string | null; summary?: string | null }, faceText: string): { title: string; summary: string } {
  const title = (run.title ?? '').trim();
  return title ? { title, summary: (run.summary ?? '').trim() } : { title: faceText, summary: '' };
}
