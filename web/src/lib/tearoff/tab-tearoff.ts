import { sessions } from '../../opscenter/api';
import { primarySessionId } from '../../opscenter/api/host';
import { PRIMARY_SLOT } from '../../opscenter/engine/model';
import { terminalLayout } from '../../opscenter/engine/layout.svelte';
import { removeTab } from '../../opscenter/engine/tab-groups.svelte';
import { t } from '../i18n/index.svelte';
import { releaseTearOff, tabTearOffTarget, type ReleasePoint, type TearOffTarget } from './tearoff';

function primaryTarget(): TearOffTarget | null {
  const id = primarySessionId();
  const row = (sessions.data ?? []).find((one) => one.session?.id === id)?.session_row_id;
  return typeof row === 'number' && Number.isFinite(row) ? { kind: 'terminal', id: String(row) } : null;
}

export function tearOffTab(tab: string, up: ReleasePoint): boolean {
  const target = tab === PRIMARY_SLOT ? primaryTarget() : tabTearOffTarget(tab);
  const pending = releaseTearOff(window, target, up);
  if (!pending) return false;
  void pending.then((opened) => {
    if (!opened) return;
    if (tab === PRIMARY_SLOT) (globalThis as { App?: { goHome?: () => void } }).App?.goHome?.();
    else removeTab(terminalLayout, tab);
    terminalLayout.announce(t('opscenter.tabs.torn_out'));
  });
  return true;
}
