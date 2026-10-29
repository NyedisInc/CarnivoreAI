import type { AutomationTarget, Targets } from '../api';
import { TARGET_FORMS } from '../target-forms';

export interface Idea {
  n: number;
  kind: 'agent' | 'command' | 'session_message' | 'swarm_card';
  cron: string;
}

export const IDEAS: readonly Idea[] = [
  { n: 1, kind: 'agent', cron: '30 7 * * 1-5' },
  { n: 2, kind: 'agent', cron: '0 6 * * *' },
  { n: 3, kind: 'swarm_card', cron: '0 9 * * 1' },
  { n: 4, kind: 'agent', cron: '0 17 * * 2#3' },
  { n: 5, kind: 'session_message', cron: '0 16 * * 1-5' },
  { n: 6, kind: 'command', cron: '0 2 * * *' },
];

export const TEXT_FIELD: Readonly<Record<string, string>> = { agent: 'prompt', command: 'command', session_message: 'text', swarm_card: 'title' };

export function ideaTarget(kind: Idea['kind'], text: string, targets: Targets): AutomationTarget | null {
  const blank = targets.kinds.includes(kind) ? (TARGET_FORMS[kind]?.blank(targets) ?? null) : null;
  return blank ? { ...blank, [TEXT_FIELD[kind] as string]: text } : null;
}

export function offeredIdeas(targets: Targets): Idea[] {
  return IDEAS.filter((i) => targets.kinds.includes(i.kind) && TARGET_FORMS[i.kind]?.blank(targets) != null);
}
