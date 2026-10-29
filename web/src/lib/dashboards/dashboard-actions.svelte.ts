import { homeBoards, viewBoard } from '../../opscenter/engine/home-sync.svelte';
import { MAX_BOARDS, cleanBoardName } from '../../opscenter/engine/home-boards';
import { resetLayout } from '../../opscenter/engine/model';
import { META } from '../../opscenter/engine/meta';
import { changeBoard } from '../../opscenter/layout-editor/editor.svelte';
import { exportBoard, refusalOf } from '../../opscenter/layout-editor/board-transfer';
import { openDashboardPopout } from '../../popout/popout';
import { openHome } from '../../opscenter/api/host';
import { t } from '../i18n/index.svelte';
import { activateDashboard, createDashboard, deleteDashboard, renameDashboard } from './api';

export const dashboardsUi: { busy: boolean; notice: string } = $state({ busy: false, notice: '' });

export function dashboardsFull(): boolean {
  return homeBoards.list.length >= MAX_BOARDS;
}

export function dashboardName(id: string): string {
  return homeBoards.list.find((board) => board.id === id)?.name ?? '';
}

export function sayDashboards(text: string): void {
  dashboardsUi.notice = text;
}

async function run(act: () => Promise<unknown>, done: string): Promise<boolean> {
  dashboardsUi.busy = true;
  try {
    await act();
    dashboardsUi.notice = done;
    return true;
  } catch (error) {
    dashboardsUi.notice = refusalOf(error).message;
    return false;
  } finally {
    dashboardsUi.busy = false;
  }
}

export function addDashboard(duplicate: boolean): Promise<boolean> {
  const name = t('dashboards.default_name', { n: homeBoards.list.length + 1 });
  return run(
    () => createDashboard(name, duplicate ? { copyOf: homeBoards.active } : { layout: resetLayout(META, 'home') }),
    t('dashboards.announce_created', { name }),
  );
}

export function makeHome(id: string): Promise<boolean> {
  const name = dashboardName(id);
  changeBoard(() => true);
  return run(() => activateDashboard(id), t('dashboards.announce_activated', { name }));
}

export async function renameTo(id: string, typed: string): Promise<boolean> {
  const name = cleanBoardName(typed);
  if (!name || name === dashboardName(id)) return false;
  return run(() => renameDashboard(id, name), t('dashboards.announce_renamed', { name }));
}

export function removeDashboard(id: string): Promise<boolean> {
  const name = dashboardName(id);
  return run(() => deleteDashboard(id), t('dashboards.announce_deleted', { name }));
}

export async function downloadDashboard(id: string): Promise<void> {
  const name = dashboardName(id);
  try {
    await exportBoard(id, name);
    dashboardsUi.notice = t('opscenter.boards.announce_exported', { name });
  } catch (error) {
    dashboardsUi.notice = refusalOf(error).message;
  }
}

export function showDashboard(id: string): void {
  void viewBoard(id === homeBoards.active ? null : id);
  void openHome();
}

export function openDashboard(id: string, editing: boolean): void {
  if (openDashboardPopout(id, window, editing) === null) dashboardsUi.notice = t('dashboards.popup_blocked');
}
