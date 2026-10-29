
import { subscribe } from '../../opscenter/api/events.svelte';
import type { EventFrame } from '../../opscenter/api/types';
import { t } from '../i18n/index.svelte';
import { accountName, accountSwitch } from './switch-store.svelte';

export const SWITCHED_FRAME = 'provider_account.switched';

export const SWITCHED_KIND = 'AccountSwitched';

interface SwitchedFrame {
  provider?: string;
  from_account_id?: string | null;
  to_account_id?: string;
  reason?: string;
  window_kind?: string | null;
  used_pct?: number | null;
  window_seconds?: number | null;
  session?: string;
  limit_kind?: string;
  at?: string;
}

interface ToastSurface {
  add(toast: Record<string, unknown>): void;
}

let started = false;

const LIMIT_REASONS = new Set(['limit_rotated', 'limit_continued', 'limit_resumed', 'limit_pinned', 'limit_failed']);

const SHORT_MAX_SECONDS = 5 * 3600;

function isShort(frame: SwitchedFrame): boolean {
  const seconds = frame.window_seconds;
  if (typeof seconds === 'number' && Number.isFinite(seconds) && seconds > 0) {
    return seconds <= SHORT_MAX_SECONDS;
  }
  return frame.window_kind === 'five_hour';
}

function providerName(provider: string): string {
  return provider === 'claude' || provider === 'codex' ? t(`ledger.editor.provider_${provider}`) : provider;
}

export function toastFor(frame: SwitchedFrame): Record<string, unknown> | null {
  if (!frame.to_account_id || !frame.provider) return null;
  const params = {
    provider: providerName(frame.provider),
    from: accountName(frame.from_account_id ?? null),
    to: accountName(frame.to_account_id),
    percent: frame.used_pct ?? '',
    window: isShort(frame) ? t('account_switch.window.short') : t('account_switch.window.long'),
    session: frame.session ?? '',
    limit: t(`account_switch.limit.${frame.limit_kind ?? 'other'}`),
  };
  const reason = frame.reason ?? '';
  const kind = reason === 'auto' || reason === 'auto_restart' || LIMIT_REASONS.has(reason) ? reason : 'manual';
  return {
    id: `acctswitch:${frame.provider}:${frame.to_account_id}:${frame.at ?? Date.now()}`,
    session_id: null,
    kind: SWITCHED_KIND,
    title: t(`account_switch.toast.title_${kind}`),
    body: t(`account_switch.toast.body_${kind}`, params),
    session_label: t('account_switch.toast.surface'),
    local: true,
  };
}

export function startSwitchToasts(): void {
  if (started) return;
  started = true;
  subscribe(SWITCHED_FRAME, (frame: EventFrame) => {
    void accountSwitch.refresh(true);
    const toast = toastFor(frame as unknown as SwitchedFrame);
    const surface = (globalThis as { ToastManager?: ToastSurface }).ToastManager;
    if (!toast || !surface || typeof surface.add !== 'function') return;
    surface.add(toast);
  });
}
