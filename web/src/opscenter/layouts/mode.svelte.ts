import { LAYOUT_KEY_PREFIX } from '../engine/session-layouts';
import type { LayoutMember } from './api';

export const PENDING_KEY = `${LAYOUT_KEY_PREFIX}@pending`;

export function layoutKeyOf(uuid: string): string {
  return `${LAYOUT_KEY_PREFIX}${uuid}`;
}

export interface LayoutMode {
  uuid: string;
  name: string;
  revision: number;
  members: LayoutMember[];
  anchorRowId: number | null;
  anchorSessionId: string;
  anchorTmux: string;
  phoneTab: string;
  naming: boolean;
  holding: boolean;
}

export const layoutMode: LayoutMode = $state({
  uuid: '',
  name: '',
  revision: 0,
  members: [],
  anchorRowId: null,
  anchorSessionId: '',
  anchorTmux: '',
  phoneTab: '',
  naming: false,
  holding: false,
});

export function layoutActive(): boolean {
  return layoutMode.uuid !== '';
}

export function memberForRow(rowId: number | null): LayoutMember | null {
  if (rowId === null) return null;
  return layoutMode.members.find((one) => one.session_row_id === rowId) ?? null;
}

export function clearLayoutMode(): void {
  layoutMode.uuid = '';
  layoutMode.name = '';
  layoutMode.revision = 0;
  layoutMode.members = [];
  layoutMode.anchorRowId = null;
  layoutMode.anchorSessionId = '';
  layoutMode.anchorTmux = '';
  layoutMode.phoneTab = '';
  layoutMode.holding = false;
}
