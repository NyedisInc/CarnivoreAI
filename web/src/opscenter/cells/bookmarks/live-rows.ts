export function liveRowIds(infos: readonly { session_row_id?: number | null; activity_status?: string | null }[]): Set<number> {
  const out = new Set<number>();
  for (const info of infos) {
    if (typeof info.session_row_id === 'number' && info.activity_status !== 'dead') out.add(info.session_row_id);
  }
  return out;
}
