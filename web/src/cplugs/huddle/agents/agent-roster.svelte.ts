import { authFetch, resourcePush } from '../../sdk';

export const ROSTER_TOPIC = 'swarm_roster';
const LIVENESS = '$live';

export interface RosterAgent {
  id: number;
  display_name: string;
  rank: string;
  state: 'asleep' | 'waking' | 'awake' | 'sleeping' | 'torn_down';
  thread_key: string;
  harness?: string | null;
  session_id?: string | null;
  parent_id?: number | null;
  character_seed?: number | null;
  color_slot?: number | null;
  color_chosen?: boolean | null;
  shape?: string | null;
  tile_bg?: number | null;
  alert?: string | null;
  question_waiting?: boolean | null;
  alert_reason?: string | null;
  activity?: string | null;
  activity_at?: number | null;
  talking_with?: number | null;
  tmux_session?: string | null;
  session_row_id?: number | null;
  session_uuid?: string | null;
  project_id?: number | null;
  company_id?: number | null;
  job?: string | null;
  effort?: string | null;
}

export const swarmRoster = $state<{ agents: RosterAgent[]; read: boolean; threadsReady: boolean | null }>({ agents: [], read: false, threadsReady: null });

let users = 0;
let off: (() => void) | null = null;
let reading = false;
let again = false;

export async function refreshRoster(): Promise<void> {
  if (reading) {
    again = true;
    return;
  }
  reading = true;
  try {
    const answer = await authFetch<{ agents?: RosterAgent[]; threads_ready?: boolean }>('/swarm/roster');
    swarmRoster.threadsReady = typeof answer.threads_ready === 'boolean' ? answer.threads_ready : null;
    swarmRoster.agents = (Array.isArray(answer.agents) ? answer.agents : []).filter((agent) => agent.state !== 'torn_down');
  } catch (error) {
    swarmRoster.agents = [];
    swarmRoster.threadsReady = null;
    console.debug('cplug.huddle: the swarm roster could not be read', error);
  } finally {
    swarmRoster.read = true;
    reading = false;
  }
  if (again) {
    again = false;
    await refreshRoster();
  }
}

export function startSwarmRoster(): () => void {
  users += 1;
  if (users === 1) {
    off = resourcePush().onChange((topics) => {
      if (topics.includes(ROSTER_TOPIC) || topics.includes(LIVENESS)) void refreshRoster();
    });
    void refreshRoster();
  }
  let stopped = false;
  return () => {
    if (stopped) return;
    stopped = true;
    users -= 1;
    if (users === 0) {
      off?.();
      off = null;
    }
  };
}

export function projectHasAgent(projectId: number | null): boolean {
  return projectId !== null && swarmRoster.agents.some((agent) => agent.rank === 'project' && agent.thread_key === String(projectId));
}
