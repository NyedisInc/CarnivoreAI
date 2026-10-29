import { t } from '../../../lib/i18n/index.svelte';

export const TL_PREFIX = 'opscenter.cell.timeline.view.';

export function tx(key: string, vars?: Record<string, string | number>): string {
  return t(TL_PREFIX + key, vars);
}
