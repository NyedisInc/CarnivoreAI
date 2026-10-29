import { authFetch } from '../../opscenter/api/auth.svelte';
import { resource, type Resource } from '../../opscenter/api/poll.svelte';
import { t } from '../i18n/index.svelte';

export interface SwarmSwitchStatus {
  enabled: boolean;
}

export const swarmSwitch = $state<{ data: SwarmSwitchStatus | null }>({ data: null });
let live: Resource<SwarmSwitchStatus> | null = null;

export function startSwarmSwitch(): void {
  if (live) return;
  live = resource<SwarmSwitchStatus>(
    () => authFetch<SwarmSwitchStatus>('/swarm/switch'),
    { intervalMs: 60000, name: 'swarm-switch', topics: ['swarm_switch'], demo: () => ({ enabled: true }) },
  );
  $effect.root(() => {
    $effect(() => { swarmSwitch.data = live?.data ?? null; });
  });
}

export async function toggleSwarm(): Promise<void> {
  const current = swarmSwitch.data;
  if (!current) return;
  try {
    const next = await authFetch<SwarmSwitchStatus>('/swarm/switch', {
      method: 'PUT', body: JSON.stringify({ enabled: !current.enabled }),
    });
    swarmSwitch.data = next;
    if (live) await live.refresh(true);
  } catch (cause) {
    const text = cause instanceof Error ? cause.message : t('swarm.switch.error');
    const toast = (globalThis as { ToastManager?: { add(item: Record<string, unknown>): void } }).ToastManager;
    if (toast) toast.add({ id: `swarm-switch-error:${Date.now()}`, session_id: null,
      kind: 'SwarmSwitchError', title: t('swarm.switch.error'), body: text, local: true });
    else console.warn('[swarm-switch]', text);
  }
}
