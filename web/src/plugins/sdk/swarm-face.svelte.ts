import type { Component } from 'svelte';

export type MemberState =
  | 'asleep' | 'unknown' | 'dead' | 'alert_immediate' | 'startup_gate' | 'question' | 'notice'
  | 'working_subagent' | 'working' | 'finished_unread' | 'idle';

export interface SwarmFaceProps {
  state: MemberState;
  agentId: number;
  rank: string;
  seed: number;
  size: number;
}

export const swarmFace = $state<{ component: Component<SwarmFaceProps> | null }>({ component: null });

export function registerSwarmFace(component: Component<SwarmFaceProps>): void {
  swarmFace.component = component;
}

export function unregisterSwarmFace(): void {
  swarmFace.component = null;
}
