import type { AutomationTarget } from './api';

export const UNATTENDED_PHRASE = 'run unattended with no permission prompts';

export const LEVELS = ['read_only', 'edits_in_folder', 'unattended'] as const;
export type Level = (typeof LEVELS)[number];

export const EFFORTS = ['low', 'medium', 'high', 'xhigh', 'max'] as const;

const READ_TOOLS = ['Read', 'Grep', 'Glob', 'WebSearch', 'WebFetch'];

export function toolsFor(level: Level): string[] {
  if (level === 'read_only') return [...READ_TOOLS];
  return level === 'edits_in_folder' ? [...READ_TOOLS, 'Edit', 'Write'] : [...READ_TOOLS, 'Edit', 'Write', 'Bash'];
}

export function blankAgent(): AutomationTarget {
  return { kind: 'agent', folder: '', prompt: '', permission: 'read_only', tools: toolsFor('read_only'), max_turns: 30, max_budget_usd: 1, timeout_s: 1800 };
}

export function agentReady(target: AutomationTarget): boolean {
  if (!String(target.folder ?? '').trim() || !String(target.prompt ?? '').trim()) return false;
  return target.permission !== 'unattended' || target.acknowledge_unattended === UNATTENDED_PHRASE;
}
