/*  hidden  */
import { readFlag, writeFlag } from '../ui/prefs.svelte';

export type LedgerFold = 'compact' | 'expanded' | 'hidden' | 'glance';

export const FOLDS: readonly LedgerFold[] = ['glance', 'hidden', 'compact', 'expanded'];

const FOLD_KEYS: Readonly<Record<Exclude<LedgerFold, 'compact'>, string>> = {
  expanded: 'ledger_expanded',
  hidden: 'ledger_hidden',
  glance: 'ledger_glance',
};

/*  hidden  */
const OPEN_KEY = 'carnivore.usagePanel.open';
const LEGACY_HIDDEN_KEY = 'carnivore.usagePanel.hidden';
const LEGACY_GLANCE_KEY = 'carnivore.usagePanel.glance';

interface FoldStore {
  isCollapsed(key: string): boolean;
  toggleCollapsed(key: string): boolean;
}

function foldStore(): FoldStore | null {
  return (globalThis as { SessionSidebarStore?: FoldStore }).SessionSidebarStore ?? null;
}

export function readFold(): LedgerFold {
  const store = foldStore();
  if (store) {
    if (store.isCollapsed(FOLD_KEYS.glance)) return 'glance';
    if (store.isCollapsed(FOLD_KEYS.hidden)) return 'hidden';
    return store.isCollapsed(FOLD_KEYS.expanded) ? 'expanded' : 'compact';
  }
  if (readFlag(LEGACY_GLANCE_KEY)) return 'glance';
  if (readFlag(LEGACY_HIDDEN_KEY)) return 'hidden';
  return readFlag(OPEN_KEY) ? 'expanded' : 'compact';
}

export function writeFold(fold: LedgerFold): void {
  const store = foldStore();
  if (store) {
    for (const [name, key] of Object.entries(FOLD_KEYS)) {
      if (store.isCollapsed(key) !== (name === fold)) store.toggleCollapsed(key);
    }
    return;
  }
  writeFlag(OPEN_KEY, fold === 'expanded');
  writeFlag(LEGACY_HIDDEN_KEY, fold === 'hidden');
  writeFlag(LEGACY_GLANCE_KEY, fold === 'glance');
}

/* wraps to the first */
export function nextFold(fold: LedgerFold): LedgerFold {
  return FOLDS[(FOLDS.indexOf(fold) + 1) % FOLDS.length]!;
}
