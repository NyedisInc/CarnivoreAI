import type { VisitorAnswerBody, VisitorPromptAnswer, VisitorRevision } from './board-visitor-revisions.svelte';
import type { AnswerRow, BoardPrompt, BoardRevision } from './board-model';
import { answerWords } from './tray-model';

export interface VisitorLine { id: string; label: string; value: string; note: string }

export function visitorsOf(rows: readonly VisitorRevision[], revision: string): VisitorRevision[] {
  return rows.filter((row) => row.revision === revision).sort((a, b) => a.number - b.number);
}

export function visitorAnswer(body: VisitorAnswerBody, prompt: string): AnswerRow | null {
  const found: VisitorPromptAnswer | undefined = body.answers?.find((a) => a.prompt === prompt);
  return found ? { prompt: found.prompt, options: found.options ?? null, checked: found.checked ?? null, text: found.text ?? null, note: found.note ?? '' } : null;
}

export function promptWords(prompt: BoardPrompt, body: VisitorAnswerBody, yes: string, no: string): string {
  const answer = visitorAnswer(body, prompt.id);
  return answer ? answerWords(prompt, answer, yes, no) : '';
}

type Labelled = { id: string; label?: unknown; title?: unknown; options?: Array<{ id: string; label?: unknown }> | null; choices?: Array<{ id: string; label?: unknown }> | null };

function valueText(value: unknown, labels: ReadonlyMap<string, string>): string {
  if (typeof value === 'string') return labels.get(value) ?? value;
  if (typeof value === 'boolean' || typeof value === 'number') return String(value);
  if (Array.isArray(value)) return value.map((v) => valueText(v, labels)).join(', ');
  return JSON.stringify(value) ?? '';
}

export function payloadLines(revision: BoardRevision, body: VisitorAnswerBody): VisitorLine[] {
  const payload = body.payload;
  if (!payload) return [];
  const values = (payload.values && typeof payload.values === 'object' ? payload.values : null) as Record<string, unknown> | null;
  const notes = (payload.notes && typeof payload.notes === 'object' ? payload.notes : {}) as Record<string, unknown>;
  const layer = revision.layer;
  if (!layer || !values) {
    return Object.entries(payload).map(([key, value]) => ({ id: key, label: key, value: valueText(value, new Map()), note: '' }));
  }
  const shared = (layer.choices ?? []) as Labelled['choices'];
  const items = ((layer.kind === 'rows' ? layer.rows : layer.items) ?? []) as unknown as Labelled[];
  return items.filter((item) => item.id in values || typeof notes[item.id] === 'string').map((item) => {
    const options = [...(item.options ?? []), ...(item.choices ?? shared ?? [])];
    const labels = new Map(options.map((o) => [o.id, typeof o.label === 'string' ? o.label : o.id]));
    const label = typeof item.label === 'string' ? item.label : typeof item.title === 'string' ? item.title : item.id;
    return { id: item.id, label, value: item.id in values ? valueText(values[item.id], labels) : '', note: typeof notes[item.id] === 'string' ? (notes[item.id] as string) : '' };
  });
}
