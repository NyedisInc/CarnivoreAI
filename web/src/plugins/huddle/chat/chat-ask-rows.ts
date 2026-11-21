import type { HuddleItem, TaskManagerMessage } from '../huddle-model';
import { isAnswered, type AskQuestion, type AskValue } from '../ask/ask-model';
import { mdPlain } from '../task-manager-markdown';

export function ownAnswer(question: AskQuestion, value: AskValue | undefined, yesNo: readonly [string, string]): string {
  if (!value || !isAnswered(question, value)) return '';
  const label = (id: string): string => mdPlain(question.options?.find((o) => o.id === id)?.label ?? id);
  switch (question.type) {
    case 'yes_no': {
      const pair = question.labels ?? yesNo;
      return mdPlain((value.value ? pair[0] : pair[1]) ?? '');
    }
    case 'single': return value.choice ? label(value.choice) : (value.other ?? '').trim();
    case 'multi': return [...(value.choices ?? []).map(label), ...(value.other?.trim() ? [value.other.trim()] : [])].join(' + ');
    case 'rank': return (value.order ?? []).map(label).join(' > ');
    default: return (value.text ?? '').trim();
  }
}

export function formQuestion(item: HuddleItem): TaskManagerMessage | null {
  for (let at = item.thread.length - 1; at >= 0; at -= 1) {
    const message = item.thread[at];
    if (message && message.kind === 'question' && !message.answered && message.form?.length) return message;
  }
  return null;
}
