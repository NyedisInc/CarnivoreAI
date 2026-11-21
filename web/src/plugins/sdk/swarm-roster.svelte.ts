
export interface SwarmRosterAgent {
  id: number;
  rank: string;
  state?: string;
  session_uuid?: string | null;
  character_seed?: number | null;
}

export interface SwarmRosterReader {
  agents: () => readonly SwarmRosterAgent[];
  refresh: () => Promise<void>;
}

const holder = $state<{ reader: SwarmRosterReader | null }>({ reader: null });

export function registerSwarmRoster(reader: SwarmRosterReader): void {
  holder.reader = reader;
}

export function unregisterSwarmRoster(): void {
  holder.reader = null;
}

export function swarmRosterAgents(): readonly SwarmRosterAgent[] {
  return holder.reader?.agents() ?? [];
}

export async function refreshSwarmRoster(): Promise<void> {
  await holder.reader?.refresh();
}
