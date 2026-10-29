import { cplugPopoutTabs } from '../../cplugs/host/readers';
import type { DynamicTabDef } from './types';

export const POPOUT_TABS: readonly DynamicTabDef[] = [...cplugPopoutTabs()];

export function popoutTab(id: string): DynamicTabDef | null {
  return POPOUT_TABS.find((def) => def.id === id && def.popout === true) ?? null;
}
