
export type AskType = 'yes_no' | 'single' | 'multi' | 'rank' | 'short_text' | 'long_text' | 'datetime';

export interface AskOption {
  id: string;
  label: string;
  recommended?: boolean;
  reason?: string;
}

export interface AskRecommend {
  value?: boolean;
  order?: string[];
  text?: string;
  reason?: string;
}

export interface AskCommand {
  text: string;
  lang?: string;
}

export interface AskQuestion {
  id: string;
  type: AskType;
  prompt: string;
  required: boolean;
  help?: string;
  labels?: string[];
  options?: AskOption[];
  other?: boolean;
  min?: number;
  max?: number;
  max_length?: number;
  placeholder?: string;
  recommend?: AskRecommend;
  command?: AskCommand;
}

export interface AskValue {
  value?: boolean;
  choice?: string | null;
  choices?: string[];
  order?: string[];
  text?: string;
  other?: string;
  note?: string;
  touched?: boolean;
  files?: { id: string; name: string }[];
}

export type AskValues = Record<string, AskValue>;

export interface AskProgress {
  total: number;
  done: number;
  requiredLeft: number;
}

export const EXTRA_KEY = '_extra';

const filled = (text: string | undefined): boolean => (text ?? '').trim().length > 0;

export function isAnswered(question: AskQuestion, value: AskValue | undefined): boolean {
  if (!value) return false;
  switch (question.type) {
    case 'yes_no': return typeof value.value === 'boolean';
    case 'single': return !!value.choice || filled(value.other);
    case 'multi': return (value.choices?.length ?? 0) > 0 || filled(value.other);
    case 'rank': return value.touched === true && (value.order?.length ?? 0) > 0;
    default: return filled(value.text);
  }
}

export function progress(questions: readonly AskQuestion[], values: AskValues): AskProgress {
  const done = questions.filter((q) => isAnswered(q, values[q.id])).length;
  const requiredLeft = questions.filter((q) => q.required && !isAnswered(q, values[q.id])).length;
  return { total: questions.length, done, requiredLeft };
}

export function hasRecommendation(question: AskQuestion): boolean {
  if (question.type === 'single' || question.type === 'multi') return (question.options ?? []).some((o) => o.recommended);
  return question.recommend !== undefined;
}

export function takeRecommendation(question: AskQuestion): AskValue | null {
  const options = question.options ?? [];
  switch (question.type) {
    case 'yes_no': return typeof question.recommend?.value === 'boolean' ? { value: question.recommend.value } : null;
    case 'single': { const pick = options.find((o) => o.recommended); return pick ? { choice: pick.id } : null; }
    case 'multi': { const picks = options.filter((o) => o.recommended).map((o) => o.id); return picks.length ? { choices: picks } : null; }
    case 'rank': return question.recommend?.order ? { order: [...question.recommend.order], touched: true } : null;
    default: return filled(question.recommend?.text) ? { text: question.recommend?.text ?? '' } : null;
  }
}

export function takeAll(questions: readonly AskQuestion[], values: AskValues): AskValues {
  const out: AskValues = { ...values };
  for (const q of questions) {
    if (isAnswered(q, out[q.id])) continue;
    const taken = takeRecommendation(q);
    if (taken) out[q.id] = { ...out[q.id], ...taken };
  }
  return out;
}

export function recommendable(questions: readonly AskQuestion[], values: AskValues): number {
  return questions.filter((q) => !isAnswered(q, values[q.id]) && takeRecommendation(q) !== null).length;
}

export function startingOrder(question: AskQuestion): string[] {
  return question.recommend?.order ? [...question.recommend.order] : (question.options ?? []).map((o) => o.id);
}

export function moveInOrder(order: readonly string[], id: string, by: -1 | 1): string[] {
  const from = order.indexOf(id);
  const to = from + by;
  const out = [...order];
  if (from < 0 || to < 0 || to >= out.length) return out;
  [out[from], out[to]] = [out[to] as string, out[from] as string];
  return out;
}

export function optionForDigit(question: AskQuestion, key: string): string | null {
  const at = /^[1-9]$/.test(key) ? Number(key) - 1 : -1;
  return (question.options ?? [])[at]?.id ?? null;
}

export function toggleChoice(question: AskQuestion, value: AskValue | undefined, id: string): AskValue {
  const now = value?.choices ?? [];
  if (now.includes(id)) return { ...value, choices: now.filter((c) => c !== id) };
  if (question.max !== undefined && now.length >= question.max) return { ...value, choices: now };
  return { ...value, choices: [...now, id] };
}

export function tookRecommendation(question: AskQuestion, value: AskValue | undefined): boolean | null {
  const rec = takeRecommendation(question);
  if (!rec || !value) return null;
  switch (question.type) {
    case 'yes_no': return value.value === rec.value;
    case 'single': return value.choice === rec.choice;
    case 'multi': return JSON.stringify([...(value.choices ?? [])].sort()) === JSON.stringify([...(rec.choices ?? [])].sort()) && !filled(value.other);
    case 'rank': return JSON.stringify(value.order) === JSON.stringify(rec.order);
    default: return value.text === rec.text;
  }
}

export function payloadOf(questions: readonly AskQuestion[], values: AskValues, extra = '', extraFileIds: readonly string[] = []): Record<string, Record<string, unknown>> {
  const out: Record<string, Record<string, unknown>> = {};
  for (const q of questions) {
    const v = values[q.id];
    const note = {
      ...(filled(v?.note) ? { note: (v?.note ?? '').trim() } : {}),
      ...(v?.files?.length ? { file_ids: v.files.map((f) => f.id) } : {}),
    };
    if (!v || !isAnswered(q, v)) {
      if (Object.keys(note).length) out[q.id] = note;
      continue;
    }
    const other = filled(v.other) ? { other: (v.other ?? '').trim() } : {};
    if (q.type === 'yes_no') out[q.id] = { value: v.value, ...note };
    else if (q.type === 'single') out[q.id] = v.choice ? { choice: v.choice, ...note } : { choice: null, ...other, ...note };
    else if (q.type === 'multi') out[q.id] = { choices: v.choices ?? [], ...other, ...note };
    else if (q.type === 'rank') out[q.id] = { order: v.order ?? [], ...note };
    else out[q.id] = { text: (v.text ?? '').trim(), ...note };
  }
  if (filled(extra) || extraFileIds.length) out[EXTRA_KEY] = { text: extra.trim(), ...(extraFileIds.length ? { file_ids: [...extraFileIds] } : {}) };
  return out;
}

export interface AskAnswer extends AskValue {
  label?: string;
  labels?: string[];
  prompt?: string;
  recommended?: boolean;
  skipped?: boolean;
  dismissed?: boolean;
}

export function answeredByComment(thread: ReadonlyArray<{ answers_to?: number; freeform?: boolean }>, questionId: number): boolean {
  return thread.some((m) => m.answers_to === questionId && m.freeform === true);
}

export type Translate = (key: string, params?: Record<string, string | number>) => string;

export function answerWords(answer: AskAnswer | undefined, tr: Translate): string {
  if (!answer) return '';
  if (answer.skipped) return answer.dismissed ? tr('cplug.huddle.ask.dismissed') : '';
  if (answer.order) return (answer.labels ?? answer.order).join(' > ');
  const parts: string[] = [];
  if (answer.labels) parts.push(...answer.labels);
  else if (answer.label) parts.push(answer.label);
  if (answer.text) parts.push(answer.text);
  if (answer.other) parts.push(`${tr('cplug.huddle.ask.other')}: ${answer.other}`);
  return parts.join(', ');
}

export function dismissPayload(questions: readonly AskQuestion[]): Record<string, Record<string, unknown>> {
  return Object.fromEntries(questions.map((q) => [q.id, { skipped: true, dismissed: true }]));
}

export function drawnQuestions<Q extends Pick<AskQuestion, 'command'>>(questions: readonly Q[]): Q[] {
  const command = questions.find((q) => q.command);
  return command && questions.length > 1 ? [command] : [...questions];
}

export function hiddenSkips(all: readonly AskQuestion[], drawn: readonly AskQuestion[]): Record<string, Record<string, unknown>> {
  return Object.fromEntries(all.filter((q) => !drawn.includes(q)).map((q) => [q.id, { skipped: true }]));
}

export function inlineQuestion(form: readonly AskQuestion[] | undefined): AskQuestion | null {
  const drawn = drawnQuestions(form ?? []);
  const only = drawn.length === 1 ? drawn[0] : undefined;
  if (!only) return null;
  if (only.type === 'yes_no') return only;
  return only.type === 'single' && (only.options?.length ?? 0) > 0 ? only : null;
}

export const isDismissClick = (event: { shiftKey: boolean }): boolean => event.shiftKey;
