import { authFetch } from '../../opscenter/api/auth.svelte';
import { resource, type Resource } from '../../opscenter/api/poll.svelte';
import { t } from '../i18n/index.svelte';
import { addLocalToast } from '../toast-surface';

export interface SwarmSwitchStatus {
  enabled: boolean;
}

export const swarmSwitch = $state<{ data: SwarmSwitchStatus | null }>({ data: null });

export function swarmIsOn(): boolean {
  return swarmSwitch.data?.enabled !== false;
}

let live: Resource<SwarmSwitchStatus> | null = null;
let seeded = false;

export function seedSwarmSwitch(status: SwarmSwitchStatus): void {
  seeded = true;
  swarmSwitch.data = status;
}

export function startSwarmSwitch(): void {
  if (live) return;
  live = resource<SwarmSwitchStatus>(
    () => authFetch<SwarmSwitchStatus>('/swarm/switch'),
    { intervalMs: 60000, name: 'swarm-switch', topics: ['swarm_switch'], demo: () => ({ enabled: true }) },
  );
  $effect.root(() => {
    $effect(() => {
      const answer = live?.data ?? null;
      if (!seeded) swarmSwitch.data = answer;
    });
  });
}

export async function toggleSwarm(next?: boolean): Promise<void> {
  const current = swarmSwitch.data;
  if (!current) return;
  try {
    const answer = await authFetch<SwarmSwitchStatus>('/swarm/switch', {
      method: 'PUT', body: JSON.stringify({ enabled: next ?? !current.enabled }),
    });
    swarmSwitch.data = answer;
    if (live) await live.refresh(true);
  } catch (cause) {
    const text = cause instanceof Error ? cause.message : t('swarm.switch.error');
    const shown = addLocalToast({ id: `swarm-switch-error:${Date.now()}`, session_id: null,
      kind: 'SwarmSwitchError', title: t('swarm.switch.error'), body: text, local: true });
    if (!shown) console.warn('[swarm-switch]', text);
  }
}
