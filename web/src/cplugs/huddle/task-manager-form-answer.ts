import { answerWords, EXTRA_KEY, type AskAnswer, type AskQuestion, type Translate } from './ask/ask-model';
import type { TaskManagerMessage } from './huddle-model';

export type FormAnswerState = 'answered' | 'skipped' | 'dismissed';

export interface FormAnswerRow {
  id: string;
  prompt: string;
  words: string;
  state: FormAnswerState;
  note: string;
}

export function formAnswerRows(message: Pick<TaskManagerMessage, 'answers'>, tr: Translate, form: readonly AskQuestion[] = []): FormAnswerRow[] {
  const answers = message.answers ?? {};
  const named = new Map(form.map((q) => [q.id, q.prompt]));
  const ids = [...form.map((q) => q.id).filter((id) => id in answers),
    ...Object.keys(answers).filter((id) => !named.has(id) && id !== EXTRA_KEY), ...(EXTRA_KEY in answers ? [EXTRA_KEY] : [])];
  return ids.map((id) => {
    const a: AskAnswer = answers[id] ?? {};
    const skipped = a.skipped === true;
    const words = skipped ? '' : (answerWords(a, tr) || (typeof a.value === 'boolean' ? tr(a.value ? 'cplug.huddle.ask.yes' : 'cplug.huddle.ask.no') : ''));
    const state: FormAnswerState = a.dismissed ? 'dismissed' : skipped || !words ? 'skipped' : 'answered';
    return { id, prompt: id === EXTRA_KEY ? '' : (a.prompt ?? named.get(id) ?? id), words, state, note: (a.note ?? '').trim() };
  });
}
