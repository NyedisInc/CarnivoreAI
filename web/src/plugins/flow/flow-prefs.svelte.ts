/* the Task Manager */
import { cplugRow, followCplugRow, refreshEnablement } from '../sdk';

export const SHOW_TAB = 'showTab';

export const flowPrefs = $state<{ showTab: boolean }>({ showTab: false });

export function adopt(row: { settings?: Record<string, unknown> } | null | undefined): void {
  if (!row) return;
  flowPrefs.showTab = row.settings?.[SHOW_TAB] === true;
}

export async function refreshFlowPrefs(): Promise<void> {
  await refreshEnablement();
  adopt(cplugRow('flow'));
}

let following = false;

export function followFlowPrefs(): void {
  if (following) return;
  following = true;
  followCplugRow('flow', (row) => adopt(row), {
    onReset: () => {
      following = false;
      flowPrefs.showTab = false;
    },
  });
}
