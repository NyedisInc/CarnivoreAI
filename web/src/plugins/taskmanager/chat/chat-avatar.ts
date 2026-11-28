import { swarmRoster, type RosterAgent } from '../agents/agent-roster.svelte';
import { colorBook } from '../swarm/agent-colors.svelte';
import type { AgentColor } from '../swarm/characters';
import { seedOf } from '../swarm/panel-state';
import { floorSource } from '../../sdk';

export function rosterAgent(id: number | null): RosterAgent | null {
  return id === null ? null : (swarmRoster.agents.find((a) => a.id === id) ?? null);
}

export function rosterIdOfName(name: string): number | null {
  const hits = swarmRoster.agents.filter((a) => a.display_name === name);
  return hits.length === 1 ? (hits[0]?.id ?? null) : null;
}

export function rosterIdOfUuid(uuid: string): number | null {
  return uuid ? (swarmRoster.agents.find((a) => a.session_uuid === uuid)?.id ?? null) : null;
}

export function avatarColorOf(agent: RosterAgent | null): AgentColor | null {
  return agent ? colorBook(swarmRoster.agents, floorSource()).of(agent) : null;
}

export function avatarSeedOf(agent: RosterAgent | null, name: string): number | string {
  return agent ? seedOf(agent) : name;
}

export function initialsOf(name: string): string {
  const letters = name.trim().split(/[\s._-]+/).filter(Boolean).slice(0, 2).map((word) => word[0]!.toUpperCase()).join('');
  return letters || '?';
}
