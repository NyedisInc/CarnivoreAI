
import type { CarryTarget } from './drawer-carry';

export type DuplicateKind = 'copy' | 'one' | 'here';

export interface DuplicateFacts {
  family: boolean;
  onScreen: boolean;
  inGlance: string | null;
  repeatable: boolean;
}

export function duplicateKind(target: CarryTarget, facts: DuplicateFacts): DuplicateKind | null {
  if (facts.family) return null;
  if (target.area === 'surface') return facts.onScreen ? 'one' : null;
  if (target.area === 'zone' || target.area === 'rail') return target.moves !== null ? 'one' : null;
  if (target.moves !== null) return 'one';
  return facts.repeatable && facts.inGlance !== null ? 'copy' : null;
}

export interface DuplicateAsk {
  kind: DuplicateKind;
  title: string;
  x: number;
  y: number;
  onCopy?: () => void;
  onMove?: () => void;
}

export const duplicatePrompt = $state<{ ask: DuplicateAsk | null }>({ ask: null });

export function askDuplicate(ask: DuplicateAsk): void {
  duplicatePrompt.ask = ask;
}

export function closeDuplicate(): void {
  duplicatePrompt.ask = null;
}

export function answerDuplicate(answer: 'copy' | 'move'): void {
  const ask = duplicatePrompt.ask;
  duplicatePrompt.ask = null;
  if (!ask) return;
  if (answer === 'copy') ask.onCopy?.();
  else ask.onMove?.();
}
