import { sessions } from '../../api';
import type { MenuNode } from '../../../lib/drawer-tabs/add-component-menu';
import { t } from '../../../lib/i18n/index.svelte';
import { pageIdOfTab } from '../../engine/page-tabs';
import { rowIdOfSlot } from '../../engine/slot-identity';
import { asleepRows } from '../running-sessions/asleep';
import { openBrowserItemMenu, openRowMenu, uuidOfTmuxName } from '../terminal-live/row-menu';
import { rowFor } from '../terminal-viewer/meta';
import { pageTabState } from './page-tab-state.svelte';

type SleepingRecord = Parameters<typeof asleepRows>[0][number];

export interface TabContextDeps {
  sessionOf(tab: string): string;
  sleepingFor(rowId: number | null): SleepingRecord | null;
  close(tab: string): void;
}

export function createTabContextMenu(deps: TabContextDeps) {
  let anchor = $state<HTMLElement | null>(null);
  let tab = $state<string | null>(null);

  const nodes = $derived<MenuNode[]>(
    tab === null ? [] : [{ id: 'close', label: t('opscenter.tabs.menu_close'), run: () => { const target = tab!; anchor = null; tab = null; deps.close(target); } }],
  );

  function close(): void {
    anchor = null;
    tab = null;
  }

  function openSmall(target: string, button: HTMLElement): boolean {
    tab = target;
    anchor = button;
    return true;
  }

  function open(target: string, button: HTMLElement, point: { x: number; y: number } | null): boolean {
    const where = point ? { point } : {};
    const pageId = pageIdOfTab(target);
    if (pageId !== null) {
      const { kind, title } = pageTabState(pageId);
      if (kind === 'file' || kind === 'page' || kind === 'browser') return openBrowserItemMenu(kind, pageId, title, button, where);
      return openSmall(target, button);
    }
    const row = rowFor(sessions.data, deps.sessionOf(target));
    if (row?.tmux_session) return openRowMenu(row, uuidOfTmuxName(row.tmux_session), button, where);
    const sleeping = deps.sleepingFor(rowIdOfSlot(target));
    const asleepRow = sleeping ? asleepRows([sleeping], new Set())[0] : undefined;
    if (asleepRow) return openRowMenu(asleepRow, asleepRow.session_uuid, button, where);
    return openSmall(target, button);
  }

  return {
    get anchor() {
      return anchor;
    },
    get nodes() {
      return nodes;
    },
    open,
    close,
  };
}
