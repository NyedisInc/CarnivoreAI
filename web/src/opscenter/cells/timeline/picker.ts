import type { SessionInfo } from '../../api';

const ROW_PREFIX = 'row:';

export function pickValueFor(info: SessionInfo): string {
  return typeof info.session_row_id === 'number' ? `${ROW_PREFIX}${info.session_row_id}` : info.session.id;
}

export function pickedInfo(infos: readonly SessionInfo[], pick: string): SessionInfo | null {
  if (!pick) return null;
  if (pick.startsWith(ROW_PREFIX)) {
    const rowId = Number(pick.slice(ROW_PREFIX.length));
    return infos.find((info) => info.session_row_id === rowId) ?? null;
  }
  return infos.find((info) => info.session.id === pick) ?? null;
}
