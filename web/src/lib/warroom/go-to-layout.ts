import { membershipsOf, type Belongs } from '../sessions-page/memberships';

export interface LayoutWithRows {
  readonly layout_uuid: string;
  readonly name: string;
  readonly members: ReadonlyArray<{ readonly session_row_id: number; readonly session_uuid: string }>;
}

export interface LayoutChoice {
  kind: 'none' | 'one' | 'many';
  layouts: readonly Belongs[];
  sessionUuid: string;
}

export function layoutChoice(
  sessionRowId: number | null | undefined,
  layouts: readonly LayoutWithRows[],
): LayoutChoice {
  const none: LayoutChoice = { kind: 'none', layouts: [], sessionUuid: '' };
  if (typeof sessionRowId !== 'number') return none;
  const sessionUuid = layouts.flatMap((l) => l.members).find((m) => m.session_row_id === sessionRowId)?.session_uuid ?? '';
  if (!sessionUuid) return none;
  const found = membershipsOf(sessionUuid, layouts, []).layouts;
  return { kind: found.length === 0 ? 'none' : found.length === 1 ? 'one' : 'many', layouts: found, sessionUuid };
}
