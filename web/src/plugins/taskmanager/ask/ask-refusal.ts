import type { Translate } from './ask-model';
import type { AskRefusedQuestion } from './ask-api';
import { mdPlain } from '../task-manager-markdown';

const FALLBACK_RULE = 'invalid';

export interface RefusalContext {
  title: string;
  questions: ReadonlyArray<{ id: string; prompt: string }>;
  reason: string;
}

/* no longer holds */
export function refusalSentence(tr: Translate, refused: AskRefusedQuestion, context: RefusalContext): string {
  const prompt = context.questions.find((q) => q.id === refused.id)?.prompt;
  const head = `question ${refused.id}: `;
  const reason = context.reason.startsWith(head) ? context.reason.slice(head.length) : context.reason;
  const params = { task: context.title, box: prompt ? mdPlain(prompt) : refused.id, reason };
  const family = context.title.trim() ? 'cplug.huddle.ask.refused' : 'cplug.huddle.ask.refused_untitled';
  const key = `${family}.${refused.rule}`;
  const text = tr(key, params);
  return text === key ? tr(`${family}.${FALLBACK_RULE}`, params) : text;
}
