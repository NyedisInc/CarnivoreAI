import { authFetch } from '../../opscenter/api/auth.svelte';
import { resourcePush } from '../resource-push/boot';
import { t } from '../i18n/index.svelte';
import { openModal } from '../modal';
import { toggleAccountMenu } from '../drawer-hud/account-menu.svelte';
import type { AccountMenuItem, BarIndicator } from '../../cplugs/sdk/types';
import BeastConfirm from './BeastConfirm.svelte';

export interface BeastStatus {
  enabled: boolean;
  prompts?: boolean;
  since: string | null;
  until?: string | null;
  pending_count: number;
  approved_count?: number;
  auto_off_rows?: readonly string[];
}

export const BEAST_AUTO_OFF_HOURS: readonly (number | null)[] = [null, 1, 4, 8];

export const BEAST_BAR_ACTION = 'beast:';
export const BEAST_ROUTE = '/beast-mode';
export const BEAST_TOPIC = 'beast_mode';
const POLL_MS = 30000;

export const beastStatus = $state<{ data: BeastStatus | null }>({ data: null });

export function beastUntilText(status: BeastStatus | null | undefined): string {
  const until = status?.enabled ? status.until : null;
  if (!until) return '';
  const at = new Date(until);
  return Number.isNaN(at.getTime()) ? '' : at.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

export function beastAutoOff(status: BeastStatus | null | undefined): boolean {
  return status?.enabled !== true && (status?.auto_off_rows?.length ?? 0) > 0;
}

export function beastPromptsOn(status: BeastStatus | null | undefined): boolean {
  return status?.enabled === true && status.prompts === true;
}

export async function refreshBeastStatus(): Promise<void> {
  try {
    beastStatus.data = await authFetch<BeastStatus>(BEAST_ROUTE);
  } catch {
  }
}

let following = false;

export function startBeastStatus(): void {
  if (following) return;
  following = true;
  resourcePush().pushOrPoll(() => void refreshBeastStatus(), POLL_MS, [BEAST_TOPIC]);
}

function reportError(cause: unknown): void {
  const text = cause instanceof Error ? cause.message : t('beast.error');
  const toast = (globalThis as { ToastManager?: { add(item: Record<string, unknown>): void } }).ToastManager;
  if (toast) toast.add({ id: `beast-error:${Date.now()}`, session_id: null, kind: 'BeastError', title: t('beast.error'), body: text, local: true });
  else console.warn('[beast-mode]', text);
}

export async function armBeast(prompts: boolean, hours: number | null): Promise<void> {
  await authFetch(BEAST_ROUTE, { method: 'PUT', body: JSON.stringify({ enabled: true, prompts, hours }) });
}

export async function disarmBeast(): Promise<void> {
  try {
    await authFetch(BEAST_ROUTE, { method: 'PUT', body: JSON.stringify({ enabled: false }) });
  } catch (cause) {
    reportError(cause);
  }
  await refreshBeastStatus();
}

export async function openBeastConfirm(): Promise<void> {
  await refreshBeastStatus();
  await openModal(BeastConfirm, { status: beastStatus.data });
  await refreshBeastStatus();
}

export function indicatorLabel(status: BeastStatus | null | undefined): string {
  const label = t(beastPromptsOn(status) ? 'beast.indicator.on_prompts' : 'beast.indicator.on');
  const time = beastUntilText(status);
  return time ? t('beast.until', { label, time }) : label;
}

export const beastMenuItem: AccountMenuItem = {
  id: 'beast_mode',
  icon: 'bolt',
  label: () => {
    if (beastAutoOff(beastStatus.data)) return t('beast.menu.auto_off');
    const time = beastUntilText(beastStatus.data);
    return time ? t('beast.menu.until', { time }) : t('beast.menu.label');
  },
  checked: () => beastStatus.data?.enabled === true,
  run: ({ close }) => {
    if (beastStatus.data?.enabled) {
      void disarmBeast();
      return;
    }
    close();
    void openBeastConfirm();
  },
};

export const beastIndicator: BarIndicator = {
  id: 'armed',
  icon: 'bolt',
  visible: () => beastStatus.data?.enabled === true || beastAutoOff(beastStatus.data),
  label: () => (beastAutoOff(beastStatus.data) ? t('beast.indicator.auto_off') : indicatorLabel(beastStatus.data)),
  tone: () => (beastAutoOff(beastStatus.data) ? 'quiet' : 'lit'),
  run: (anchor) => toggleAccountMenu(anchor),
};
