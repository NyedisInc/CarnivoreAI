import { phaseOf, type OpView, type Phase } from './migrate-store.svelte';

export type MovePanelState = 'pick' | 'checking' | 'refused' | 'ready' | 'moving' | 'done' | 'failed';

export interface MovePanelInput {
  kind: 'project' | 'company' | 'back';
  phase: Phase;
  machine: string | null;
  busy: boolean;
  error: string | null;
  canApply: boolean | null;
  opState: string | null;
}

export function movePanelState(i: MovePanelInput): MovePanelState {
  const phase = i.opState ? phaseOf(i.opState) : i.phase;
  if (phase === 'done' || phase === 'failed') return phase;
  if (phase === 'running') return 'moving';
  if (phase === 'plan') return i.canApply === false ? 'refused' : 'ready';
  if (i.busy) return 'checking';
  if (i.error && (i.machine || i.kind === 'back')) return 'refused';
  return 'pick';
}

export function stepProgress(step: string | null, steps: string[]): { n: number; total: number } | null {
  const at = step ? steps.indexOf(step) : -1;
  return at < 0 ? null : { n: at + 1, total: steps.length };
}

export const MAX_LISTED_FILES = 20;

export interface NotCopiedFiles {
  names: string[];
  total: number;
}

export function notCopiedFiles(op: OpView | null): NotCopiedFiles {
  if (!op) return { names: [], total: 0 };
  const strings = (v: unknown): string[] => (Array.isArray(v) ? v.filter((n): n is string => typeof n === 'string') : []);
  const count = (v: unknown): number => (typeof v === 'number' && Number.isInteger(v) && v > 0 ? v : 0);
  const summary: unknown = op.detail.summary;
  const own = strings(typeof summary === 'object' && summary !== null && 'task_files_not_copied' in summary ? summary.task_files_not_copied : undefined);
  const lists = [own, ...op.children.map((c) => strings(c.task_files_not_copied))];
  const more = op.children.reduce((sum, c) => sum + count(c.task_files_not_copied_more), 0);
  const all = lists.flat();
  return { names: all.slice(0, MAX_LISTED_FILES), total: all.length + more };
}
