
import { sessionForSlot } from '../../engine/slot-identity';
import type { SessionInfo } from '../../api';

export const VIEWER_KEYS = {
  tooShort: 'opscenter.cell.terminal.viewer.too_short',
  connecting: 'opscenter.cell.terminal.viewer.connecting',
  reconnecting: 'opscenter.cell.terminal.viewer.reconnecting',
  gone: 'opscenter.cell.terminal.viewer.gone',
  open: 'opscenter.cell.terminal.viewer.open',
  readOnly: 'opscenter.cell.terminal.viewer.read_only',
  remove: 'opscenter.menu.remove',
} as const;

/* and an empty string */
export function sessionIdOf(instance: string, rows: SessionInfo[] | null): string {
  return sessionForSlot(instance, rows);
}

export function rowFor(rows: SessionInfo[] | null, sessionId: string): SessionInfo | null {
  if (!rows || !sessionId) return null;
  return rows.find((row) => row.session?.id === sessionId) ?? null;
}

export const VIEWER_ACCEPTS_INPUT = true;

export function showsReadOnlyNotice(acceptsInput: boolean, dead: boolean): boolean {
  return !acceptsInput && !dead;
}

export interface Letterbox {
  scale: number;
  left: number;
  top: number;
}

export const MAX_VIEWER_SCALE = 2;

/* there is nothing */
export function letterbox(
  bodyWidth: number,
  bodyHeight: number,
  paneWidth: number,
  paneHeight: number,
): Letterbox {
  const fits: number[] = [];
  if (bodyWidth > 0 && paneWidth > 0) fits.push(bodyWidth / paneWidth);
  if (bodyHeight > 0 && paneHeight > 0) fits.push(bodyHeight / paneHeight);
  const scale = fits.length === 0 ? 1 : Math.min(MAX_VIEWER_SCALE, ...fits);
  return {
    scale,
    left: Math.max(0, (bodyWidth - paneWidth * scale) / 2),
    top: Math.max(0, (bodyHeight - paneHeight * scale) / 2),
  };
}

