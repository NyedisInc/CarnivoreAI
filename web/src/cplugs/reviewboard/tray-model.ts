import { newClientId } from '../sdk';
import type { AnchorNoteRow, AnswerRow, BoardPrompt, BoardRevision, BoardSidecar, DraftWire, RoundContext, RoundWire } from './board-model';

export type Draft = DraftWire;

export function newDraft(revision: string, id: string = newClientId()): Draft {
  return { rev: 0, revision, answers: [], anchor_notes: [], note: '', client_round_id: id };
}

export function answerOf(draft: Draft | null, prompt: string): AnswerRow | null {
  return draft?.answers.find((a) => a.prompt === prompt) ?? null;
}

function hasContent(prompt: BoardPrompt, a: AnswerRow): boolean {
  if (prompt.kind === 'choice' || prompt.kind === 'multi') return (a.options?.length ?? 0) > 0;
  if (prompt.kind === 'check') return a.checked === true || a.checked === false;
  return (a.text ?? '').trim().length > 0;
}

function put(draft: Draft, prompt: BoardPrompt, next: Partial<AnswerRow>): Draft {
  const old = answerOf(draft, prompt.id);
  const merged: AnswerRow = { prompt: prompt.id, note: old?.note ?? '', ...(old ?? {}), ...next };
  const rest = draft.answers.filter((a) => a.prompt !== prompt.id);
  if (!hasContent(prompt, merged)) return { ...draft, answers: rest };
  const order = (id: string): number => draft.answers.findIndex((a) => a.prompt === id);
  const answers = [...rest, merged].sort((a, b) => (order(a.prompt) < 0 ? 1e6 : order(a.prompt)) - (order(b.prompt) < 0 ? 1e6 : order(b.prompt)));
  return { ...draft, answers };
}

export function pickOption(draft: Draft, prompt: BoardPrompt, option: string): Draft {
  const held = answerOf(draft, prompt.id)?.options ?? [];
  if (prompt.kind === 'choice') return put(draft, prompt, { options: held[0] === option ? [] : [option], checked: null, text: null });
  const next = held.includes(option) ? held.filter((o) => o !== option) : [...held, option];
  return put(draft, prompt, { options: next, checked: null, text: null });
}

export function setChecked(draft: Draft, prompt: BoardPrompt, checked: boolean | null): Draft {
  return put(draft, prompt, { checked, options: null, text: null });
}

export function setText(draft: Draft, prompt: BoardPrompt, text: string): Draft {
  return put(draft, prompt, { text: text.trim() ? text : '', options: null, checked: null });
}

export function setPromptNote(draft: Draft, prompt: BoardPrompt, note: string): Draft {
  return answerOf(draft, prompt.id) ? put(draft, prompt, { note }) : draft;
}

export function setAnchorNote(draft: Draft, anchor: string, text: string): Draft {
  const rest = draft.anchor_notes.filter((n) => n.anchor !== anchor);
  return { ...draft, anchor_notes: text.trim() ? [...rest, { anchor, text }] : rest };
}

export function anchorNoteOf(draft: Draft | null, anchor: string): string {
  return draft?.anchor_notes.find((n) => n.anchor === anchor)?.text ?? '';
}

export function setNote(draft: Draft, note: string): Draft {
  return { ...draft, note };
}

export function shownRevision(sidecar: BoardSidecar, latest: BoardRevision, draft: Draft | null): BoardRevision {
  const stale = !!draft && !isDraftEmpty(draft) && draft.revision !== latest.id;
  return stale ? (sidecar.revisions.find((r) => r.id === draft.revision) ?? latest) : latest;
}

export function unansweredCount(revision: BoardRevision, draft: Draft | null): number {
  return revision.prompts.filter((p) => !answerOf(draft, p.id)).length;
}

export function draftCounts(revision: BoardRevision, draft: Draft | null): { answered: number; left: number; noted: number } {
  const left = unansweredCount(revision, draft);
  const promptNotes = revision.prompts.filter((p) => (answerOf(draft, p.id)?.note ?? '').trim() !== '').length;
  const noted = (draft?.anchor_notes.filter((n) => n.text.trim() !== '').length ?? 0) + promptNotes + (draft?.note.trim() ? 1 : 0);
  return { answered: revision.prompts.length - left, left, noted };
}

export function isDraftEmpty(draft: Draft | null): boolean {
  return !draft || (draft.answers.length === 0 && draft.anchor_notes.length === 0 && !draft.note.trim());
}

export function anchorState(revision: BoardRevision, draft: Draft | null): { answered: string[]; noted: string[] } {
  const answered = new Set(revision.prompts.filter((p) => p.anchor && answerOf(draft, p.id)).map((p) => p.anchor as string));
  return { answered: [...answered], noted: (draft?.anchor_notes ?? []).map((n) => n.anchor) };
}

export function roundBody(draft: Draft, context: RoundContext): RoundWire {
  return { client_round_id: draft.client_round_id, revision: draft.revision, answers: draft.answers, anchor_notes: draft.anchor_notes, note: draft.note, context };
}

function fits(prompt: BoardPrompt, a: AnswerRow): boolean {
  if (prompt.kind === 'choice' || prompt.kind === 'multi') {
    const known = new Set((prompt.options ?? []).map((o) => o.id));
    return (a.options ?? []).length > 0 && (a.options ?? []).every((o) => known.has(o));
  }
  return true;
}

export function carryDraft(draft: Draft, from: BoardRevision, to: BoardRevision): Draft {
  const answers: AnswerRow[] = [];
  const spill: string[] = [];
  for (const a of draft.answers) {
    const old = from.prompts.find((p) => p.id === a.prompt);
    const now = to.prompts.find((p) => p.id === a.prompt);
    if (now && old && now.kind === old.kind && fits(now, a)) answers.push(a);
    else if (old) spill.push(`${old.label}: ${a.text ?? (a.options ?? []).join(', ') ?? ''}`.trim());
  }
  const anchors = new Set(to.anchors.map((x) => x.id));
  const kept: AnchorNoteRow[] = draft.anchor_notes.filter((n) => anchors.has(n.anchor));
  for (const n of draft.anchor_notes.filter((x) => !anchors.has(x.anchor))) spill.push(`${from.anchors.find((x) => x.id === n.anchor)?.label ?? n.anchor}: ${n.text}`);
  const note = [draft.note, ...spill].filter((x) => x.trim()).join('\n');
  return { ...draft, revision: to.id, answers, anchor_notes: kept, note };
}

export interface Ghost { round: string; revision: string; answer: AnswerRow }

export function ghostFor(sidecar: BoardSidecar, prompt: BoardPrompt, before: number): Ghost | null {
  const number = (id: string): number => sidecar.revisions.find((r) => r.id === id)?.n ?? 0;
  for (const round of [...sidecar.rounds].reverse()) {
    if (number(round.revision) >= before) continue;
    const answer = round.answers.find((a) => a.prompt === prompt.id);
    if (answer) return { round: round.id, revision: round.revision, answer };
  }
  return null;
}

export function copyGhost(draft: Draft, prompt: BoardPrompt, ghost: Ghost): Draft {
  if (!fits(prompt, ghost.answer)) return draft;
  const a = ghost.answer;
  return put(draft, prompt, { options: a.options ?? null, checked: a.checked ?? null, text: a.text ?? null });
}

export function answerWords(prompt: BoardPrompt | undefined, a: AnswerRow, yes: string, no: string): string {
  if (a.checked === true || a.checked === false) return a.checked ? yes : no;
  if (a.options?.length) {
    const labels = new Map((prompt?.options ?? []).map((o) => [o.id, o.label]));
    return a.options.map((o) => labels.get(o) ?? o).join(', ');
  }
  return (a.text ?? '').trim();
}
