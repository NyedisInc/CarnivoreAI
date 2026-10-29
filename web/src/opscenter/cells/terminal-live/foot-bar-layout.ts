import { preferenceField } from '../../../lib/preferences/field';
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

export function asFootBarLayout(value: unknown): FootBarLayout {
  const record = value && typeof value === 'object' ? (value as Record<string, unknown>) : {};
  return {
    collapsed: resolveFootBarCollapsedOption(record.collapsed),
    open: resolveSessionControlOption(record.open),
  };
}

const field = preferenceField<FootBarLayout>(FOOT_BAR_LAYOUT_FIELD, asFootBarLayout, DEFAULT_FOOT_BAR_LAYOUT);

export function readFootBarLayout(): FootBarLayout {
  return field.read();
}

export function saveFootBarLayout(layout: FootBarLayout): Promise<string | null> {
  return field.save(layout);
}

/* there is nothing */
export function followFootBarLayout(apply: (layout: FootBarLayout) => void): () => void {
  return field.follow(apply);
}
