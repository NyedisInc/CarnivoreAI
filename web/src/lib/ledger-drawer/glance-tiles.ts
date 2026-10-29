import type { AccountUsage, LedgerSnapshot } from '../../opscenter/api';
import { elapsedPct } from '../../../../client/js/labels/pace.js';
import { WINDOW_SCALE_STOPS, scaleStepFor } from '../../../../client/js/labels/usage-panel.js';
import type { GlancePlacementOptions, GlanceTile, PlacementOptions } from '../drawer-zone/glance';
import type { AccountSwitchState } from '../account-switch/switch-model';
import { sortAccounts } from '../../opscenter/cells/ledger/meta';
import { longWindow, shortWindow } from './recommend';

export const ALL_ACCOUNTS = 'all';

export const ACCOUNT_OPTION = 'account';

export const GLANCE_AMBER_AHEAD_POINTS = 15;

const AMBER_STEP = 3;

export interface GlanceWindowFigure {
  usedPct: number;
  pacerPct: number | null;
  amber: boolean;
  step: number;
}

export interface ProviderGlance {
  provider: string;
  title: string;
  accountId: string;
  accountLabel: string;
  accountName: string;
  credentialState: string;
  short: GlanceWindowFigure | null;
  long: GlanceWindowFigure | null;
}

export function isAheadOfPace(usedPct: number, pacerPct: number | null): boolean {
  return pacerPct !== null && usedPct - pacerPct >= GLANCE_AMBER_AHEAD_POINTS;
}

function figureOf(window: ReturnType<typeof shortWindow>, nowMs: number): GlanceWindowFigure | null {
  if (!window) return null;
  const pacerPct = elapsedPct(window, nowMs) as number | null;
  const usedPct = Math.min(100, Math.max(0, window.used_pct));
  const amber = isAheadOfPace(window.used_pct, pacerPct);
  const step = Math.max(scaleStepFor(usedPct, WINDOW_SCALE_STOPS) as number, amber ? AMBER_STEP : 1);
  return { usedPct, pacerPct, amber, step };
}

export function providerGlanceTiles(
  snapshot: LedgerSnapshot | null,
  nowMs: number,
  options: PlacementOptions = {},
  state: AccountSwitchState | null = null,
): GlanceTile<ProviderGlance>[] {
  if (!snapshot) return [];
  const all = sortAccounts(snapshot.accounts, state);
  const only = options[ACCOUNT_OPTION];
  const chosen = typeof only === 'string' && only !== ALL_ACCOUNTS ? all.filter((account) => account.id === only) : [];
  const accounts = chosen.length > 0 ? chosen : all;
  return accounts.map((account) => {
    const ok = account.credential_state === 'ok';
    return {
      key: account.id,
      data: {
        provider: account.provider,
        title: [account.provider, account.plan].filter(Boolean).join(' '),
        accountId: account.id,
        accountLabel: account.short_name || account.name,
        accountName: account.name,
        credentialState: account.credential_state,
        short: ok ? figureOf(shortWindow(account), nowMs) : null,
        long: ok ? figureOf(longWindow(account), nowMs) : null,
      },
    };
  });
}

export function providerGlanceOptions(snapshot: LedgerSnapshot | null): GlancePlacementOptions {
  const accounts = snapshot ? sortAccounts(snapshot.accounts) : [];
  const names = new Map(accounts.map((account) => [account.id, account.short_name || account.name]));
  return {
    schema: {
      version: 1,
      fields: {
        [ACCOUNT_OPTION]: {
          kind: 'enum',
          labelKey: 'drawer_zone.glance.option.account',
          options: [ALL_ACCOUNTS, ...accounts.map((account) => account.id)],
          default: ALL_ACCOUNTS,
          control: 'select',
        },
      },
    },
    optionLabel: (key, option) => (key === ACCOUNT_OPTION ? names.get(option) : undefined),
  };
}
