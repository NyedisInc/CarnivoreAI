import { wakeOrPick } from '../../opscenter/api/asleep.svelte';
import { addLayoutMember, type LayoutMemberWrite } from './api.svelte';

interface AsleepRow {
  asleep?: boolean;
  session_uuid?: string | null;
  name?: string;
  label?: string | null;
}

export async function addMemberAndWake(layoutUuid: string, sessionUuid: string): Promise<LayoutMemberWrite> {
  const written = await addLayoutMember(layoutUuid, sessionUuid);
  const rows = (globalThis as { SessionSidebar?: { _rows?: AsleepRow[] } }).SessionSidebar?._rows ?? [];
  const row = rows.find((r) => r && r.asleep && r.session_uuid === sessionUuid);
  if (row) {
    wakeOrPick(sessionUuid, row.name ?? '', row.label || row.name || '').catch((err: unknown) => {
      console.warn('wake after add to layout failed', err);
    });
  }
  return written;
}
