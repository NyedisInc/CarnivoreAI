import type { PackMachine } from '../pack-machines/pack-machines-store.svelte';

export const isOld = (m: PackMachine): boolean => m.state === 'connected' && !m.capabilities.includes('pack.jobs');

export const isTicked = (m: PackMachine, never: readonly string[]): boolean => !isOld(m) && !never.includes(m.install_id) && !never.includes(m.label);

export interface HintFacts {
  never: boolean;
  hasCopy: boolean;
  takesWork: boolean;
  refused: string | null;
  copying: boolean;
}

/* there is nothing */
export function hintFor(m: PackMachine, f: HintFacts, t: (key: string, vars?: Record<string, string>) => string, reason: (code: string) => string): string {
  const withWork = (state: string): string => (f.takesWork ? state : t('pack.autodelegate.state.with_no_work', { state }));
  if (isOld(m)) return t('pack.autodelegate.state.old');
  if (!f.hasCopy && !f.takesWork) return t('pack.autodelegate.state.no_work');
  if (f.never) return withWork(t(f.hasCopy ? 'pack.autodelegate.state.never_has_copy' : 'pack.autodelegate.state.never'));
  if (m.state !== 'connected') return withWork(t('pack.autodelegate.state.offline'));
  if (f.refused) {
    const why = reason(f.refused);
    return withWork(why ? t('pack.autodelegate.state.refused', { reason: why }) : t('pack.autodelegate.state.refused_generic'));
  }
  if (f.copying) return t('pack.autodelegate.state.copying');
  return f.takesWork ? '' : t('pack.autodelegate.state.no_work');
}
