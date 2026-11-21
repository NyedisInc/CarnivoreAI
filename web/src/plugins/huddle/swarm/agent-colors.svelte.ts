import { floorSource, type FloorSource } from '../../sdk';
import { swarmRoster } from '../agents/agent-roster.svelte';
import { assignColors, byProject, byRandom, colorOfMember, placeFamilies, type AgentColor, type ColorMember } from './characters/family';
import { swarmLook, type ColorMode } from './characters/look-settings.svelte';
import { sessionAgent } from './floor';
import { swarmGround } from './ground.svelte';
import type { Ground } from './characters/palette';

export interface ColorAgent {
  id: number;
  rank?: string;
  company_id?: number | null;
  project_id?: number | null;
  color_slot?: number | null;
  color_chosen?: boolean | null;
  session_row_id?: number | null;
  session_uuid?: string | null;
}

export interface ColorBook {
  of(agent: ColorAgent): AgentColor;
}

export type ColorSource = Pick<FloorSource, 'companies' | 'projects' | 'sessions'>;

export function colorBook(
  agents: readonly ColorAgent[],
  source: ColorSource | null,
  mode: ColorMode = swarmLook.color_mode,
  ground: Ground = swarmGround.ground,
): ColorBook {
  const rule = mode === 'random' ? byRandom : byProject;
  const companyOfProject = new Map<number, number | null>((source?.projects ?? []).map((p) => [p.id, p.companyId]));
  const led = [...agents].sort((a, b) => a.id - b.id).flatMap((a) => (a.rank === 'project' && typeof a.project_id === 'number' ? [a.project_id] : []));
  const wheel = placeFamilies(source?.companies ?? [], led, ground);
  const memberOf = (a: ColorAgent): ColorMember => ({
    id: a.id,
    companyId: a.company_id ?? (typeof a.project_id === 'number' ? (companyOfProject.get(a.project_id) ?? null) : null),
    projectId: a.rank === 'company' || a.rank === 'alpha' ? null : (a.project_id ?? null),
    sysop: a.rank === 'alpha',
    base: a.rank === 'alpha' || a.rank === 'company' || a.rank === 'project',
    chosenSlot: a.color_chosen ? (a.color_slot ?? null) : null,
  });
  const rows = new Set(agents.flatMap((a) => (a.session_row_id != null ? [a.session_row_id] : [])));
  const uuids = new Set(agents.flatMap((a) => (a.session_uuid ? [a.session_uuid] : [])));
  const sessions: ColorMember[] = (source?.sessions ?? [])
    .filter((s) => !(s.sessionRowId != null && rows.has(s.sessionRowId)) && !(s.sessionUuid && uuids.has(s.sessionUuid)))
    .map((s) => ({
      id: sessionAgent(s).id,
      companyId: s.projectId !== null ? (companyOfProject.get(s.projectId) ?? null) : null,
      projectId: s.projectId,
      late: true,
    }));
  const book = assignColors([...agents.map(memberOf), ...sessions], wheel, rule);
  return { of: (a) => book.get(a.id) ?? colorOfMember(memberOf(a), wheel, rule) };
}

export function createAgentColors(): ColorBook {
  const book = $derived(colorBook(swarmRoster.agents, floorSource()));
  return { of: (a) => book.of(a) };
}
