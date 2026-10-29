import { phaseOf, type Phase } from './migrate-store.svelte';

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
