import { authFetch, resourcePush } from '../sdk';

const CPLUGS_TOPIC = 'cplugs';
const POLL_MS = 60_000;
export const SHOW_TAB = 'showTab';

export const flowPrefs = $state<{ showTab: boolean }>({ showTab: false });

export function adopt(row: { settings?: Record<string, unknown> } | null | undefined): void {
  if (!row) return;
  flowPrefs.showTab = row.settings?.[SHOW_TAB] === true;
}

export async function refreshFlowPrefs(): Promise<void> {
  try {
    adopt(await authFetch<{ settings?: Record<string, unknown> }>('/cplugs/flow'));
  } catch {
  }
}

let following = false;

export function followFlowPrefs(): void {
  if (following) return;
  following = true;
  const push = resourcePush();
  push.onChange((topics) => {
    if (topics.includes(CPLUGS_TOPIC)) void refreshFlowPrefs();
  });
  push.pushOrPoll(() => void refreshFlowPrefs(), POLL_MS, [CPLUGS_TOPIC]);
  void refreshFlowPrefs();
}
