
import { ApiError, authFetch } from '../../opscenter/api/auth.svelte';
import { resource, type Resource } from '../../opscenter/api/poll.svelte';
import { ledger } from '../../opscenter/api/ledger.svelte';
import { t } from '../i18n/index.svelte';
import { errorMessageOr } from '../errors/failure-reason';
import { browserLedgerHost } from '../ledger/ledger-host';
import { startLogin, type RowActionDeps } from '../ledger/row-actions';
import {
  refusalCode,
  type AccountActivated,
  type AccountSwitchState,
  type RunningElsewhere,
} from './switch-model';

export const SWITCH_POLL_MS = 30000;

function demoState(): AccountSwitchState {
  return {
    auto_switch: false,
    threshold_percent: 99,
    active: [
      { provider: 'claude', account_id: null, source: 'none', pointer: null },
      { provider: 'codex', account_id: null, source: 'none', pointer: null },
    ],
    last_switch: null,
    restarts_running_sessions: false,
  };
}

/* active account */
export const accountSwitch: Resource<AccountSwitchState> = resource<AccountSwitchState>(
  () => authFetch<AccountSwitchState>('/provider-ledger/switch'),
  { intervalMs: SWITCH_POLL_MS, name: 'account-switch', demo: demoState, topics: ['account_switch'] },
);

export const switchActivity = $state<{
  busy: string | null;
  error: string | null;
  running: RunningElsewhere[];
}>({ busy: null, error: null, running: [] });

export function accountName(id: string | null): string {
  if (!id) return t('opscenter.value.unknown');
  const row = ledger.data?.accounts.find((account) => account.id === id);
  return row ? row.short_name || row.name : id;
}

export async function setAutoSwitch(enabled: boolean): Promise<void> {
  if (switchActivity.busy) return;
  switchActivity.busy = 'auto';
  switchActivity.error = null;
  try {
    await authFetch<AccountSwitchState>('/provider-ledger/switch', {
      method: 'PUT',
      body: JSON.stringify({ auto_switch: enabled }),
    });
  } catch (error) {
    switchActivity.error = t('account_switch.error.toggle_failed', { reason: errorMessageOr(error, t('opscenter.value.read_failed')) });
  } finally {
    switchActivity.busy = null;
    await accountSwitch.refresh(true);
  }
}

export async function switchTo(id: string): Promise<AccountActivated | null> {
  if (switchActivity.busy) return null;
  switchActivity.busy = id;
  switchActivity.error = null;
  try {
    const answer = await authFetch<AccountActivated>(
      `/provider-ledger/accounts/${encodeURIComponent(id)}/activate`,
      { method: 'POST' },
    );
    switchActivity.running = answer.running_elsewhere;
    return answer;
  } catch (error) {
    const code = error instanceof ApiError ? refusalCode(error.payload) : null;
    switchActivity.error = code === 'profile_not_shared'
      ? t('account_switch.error.not_shared', { name: accountName(id) })
      : code === 'profile_needs_setup'
        ? t('account_switch.error.needs_setup', { name: accountName(id) })
        : t('account_switch.error.failed', { name: accountName(id), reason: errorMessageOr(error, t('opscenter.value.read_failed')) });
    return null;
  } finally {
    switchActivity.busy = null;
    await accountSwitch.refresh(true);
  }
}

export type SetupOutcome = 'done' | 'pending' | 'login';

const SETUP_REREAD_MS = 6000;

function openLogin(id: string): Promise<void> {
  let busy: string | null = null;
  const deps: RowActionDeps = {
    host: browserLedgerHost(),
    t,
    stored: () => null,
    busy: (_kind, value) => {
      busy = value;
    },
    isBusy: () => busy !== null,
    notice: (_id, message) => {
      if (message) switchActivity.error = message;
    },
    reread: () => ledger.refresh(true),
    close: () => {},
  };
  return startLogin(id, deps);
}

/* active account */
export async function finishSetup(
  id: string,
  login?: () => void | Promise<void>,
): Promise<SetupOutcome | null> {
  if (switchActivity.busy) return null;
  switchActivity.busy = id;
  switchActivity.error = null;
  let outcome: SetupOutcome | null = null;
  try {
    const answer = await authFetch<{ outcome: SetupOutcome }>(
      `/provider-ledger/accounts/${encodeURIComponent(id)}/setup`,
      { method: 'POST' },
    );
    outcome = answer.outcome;
    if (outcome === 'pending') {
      switchActivity.error = t('account_switch.error.setup_pending', { name: accountName(id) });
    }
  } catch (error) {
    const code = error instanceof ApiError ? refusalCode(error.payload) : null;
    switchActivity.error = code === 'profile_not_managed'
      ? t('account_switch.error.setup_not_managed', { name: accountName(id) })
      : t('account_switch.error.setup_failed', { name: accountName(id), reason: errorMessageOr(error, t('opscenter.value.read_failed')) });
  } finally {
    switchActivity.busy = null;
  }
  if (outcome === 'login') await (login ? login() : openLogin(id));
  else if (outcome) setTimeout(() => void ledger.refresh(true), SETUP_REREAD_MS);
  return outcome;
}

/* running sessions */
export async function loadRunningElsewhere(): Promise<void> {
  try {
    switchActivity.running = await authFetch<RunningElsewhere[]>('/provider-ledger/switch/running');
  } catch (error) {
    console.warn('[account switch] running sessions unavailable:', errorMessageOr(error, t('opscenter.value.read_failed')));
  }
}
