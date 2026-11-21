
export interface SwarmAgentActions {
  wake: (id: number, mode: 'fresh' | 'resume') => Promise<void>;
  rename: (id: number, displayName: string) => Promise<void>;
  turnOff: (id: number, confirmName?: string) => Promise<void>;
  openTerminal: (id: number) => Promise<boolean>;
}

export class SwarmActionsUnavailableError extends Error {
  constructor() {
    super('swarm_agent_actions_unavailable');
    this.name = 'SwarmActionsUnavailableError';
  }
}

let provider: SwarmAgentActions | null = null;

export function registerSwarmAgentActions(actions: SwarmAgentActions): void {
  provider = actions;
}

export function unregisterSwarmAgentActions(): void {
  provider = null;
}

function required(): SwarmAgentActions {
  if (!provider) throw new SwarmActionsUnavailableError();
  return provider;
}

export async function wakeSwarmAgent(id: number, mode: 'fresh' | 'resume'): Promise<void> {
  await required().wake(id, mode);
}

export async function renameSwarmAgent(id: number, displayName: string): Promise<void> {
  await required().rename(id, displayName);
}

export async function turnOffSwarmAgent(id: number, confirmName?: string): Promise<void> {
  await required().turnOff(id, confirmName);
}

export async function openSwarmAgentTerminal(id: number): Promise<boolean> {
  return provider ? provider.openTerminal(id) : false;
}
