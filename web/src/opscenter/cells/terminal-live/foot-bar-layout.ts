import {
  resolveFootBarCollapsedOption, DEFAULT_FOOT_BAR_COLLAPSED_OPTION, type FootBarCollapsedOption,
} from './foot-plan';
import {
  resolveSessionControlOption, DEFAULT_SESSION_CONTROL_OPTION, type SessionControlOption,
} from '../../../lib/session-control/control-center';

export const FOOT_BAR_LAYOUT_FIELD = 'foot_bar_layout';

export interface FootBarLayout {
  collapsed: FootBarCollapsedOption;
  open: SessionControlOption;
}

export const DEFAULT_FOOT_BAR_LAYOUT: FootBarLayout = {
  collapsed: DEFAULT_FOOT_BAR_COLLAPSED_OPTION,
  open: DEFAULT_SESSION_CONTROL_OPTION,
};

interface Bridge {
  read(field: string, localReader: () => unknown): unknown;
  write(field: string, value: unknown, localWriter: () => void): Promise<unknown>;
  follow?(field: string, apply: (value: unknown) => void): () => void;
}

function bridge(): Bridge | null {
  const found = (globalThis as { PreferenceBridge?: Bridge }).PreferenceBridge;
  return found && typeof found.read === 'function' ? found : null;
}

const SAVED = new Set(['committed', 'unchanged']);

export function asFootBarLayout(value: unknown): FootBarLayout {
  const record = value && typeof value === 'object' ? (value as Record<string, unknown>) : {};
  return {
    collapsed: resolveFootBarCollapsedOption(record.collapsed),
    open: resolveSessionControlOption(record.open),
  };
}

export function readFootBarLayout(): FootBarLayout {
  return asFootBarLayout(bridge()?.read(FOOT_BAR_LAYOUT_FIELD, () => DEFAULT_FOOT_BAR_LAYOUT));
}

export async function saveFootBarLayout(layout: FootBarLayout): Promise<string | null> {
  const found = bridge();
  if (!found) return 'unavailable';
  const result = (await found.write(FOOT_BAR_LAYOUT_FIELD, layout, () => {})) as
    { status?: string; detail?: string } | null;
  const status = result && typeof result.status === 'string' ? result.status : '';
  if (SAVED.has(status)) return null;
  return (result && result.detail) || status || 'the server did not answer';
}

export function followFootBarLayout(apply: (layout: FootBarLayout) => void): () => void {
  const found = bridge();
  if (!found || typeof found.follow !== 'function') return () => {};
  return found.follow(FOOT_BAR_LAYOUT_FIELD, (value) => apply(asFootBarLayout(value)));
}
