import type { Message } from '../../../cplugs/huddle/task-manager-design/model';

export interface Mk2Answered { answered: boolean; time: string | null }

export function answeredOf(messages: readonly Message[]): Mk2Answered | null {
  const questions = messages.map((message, at) => ({ message, at })).filter(({ message }) => message.kind === 'question');
  if (questions.length === 0) return null;
  if (questions.some(({ message }) => !message.answered)) return { answered: false, time: null };
  const newest = questions[questions.length - 1]!.at;
  const reply = messages.slice(newest + 1).find((message) => message.by === 'you' && !message.comment);
  return { answered: true, time: reply?.time || null };
}
