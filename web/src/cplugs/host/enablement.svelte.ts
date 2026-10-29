import { authFetch, resourcePush } from '../sdk';
import type { CplugManifest } from '../sdk';

export const POLL_MS = 60_000;
export const CPLUGS_TOPIC = 'cplugs';
const DEFAULT_GRANTED = new Set(['sessions.read', 'notify']);

export const cplugEnablement = $state<{ read: boolean; enabled: Record<string, boolean> }>({ read: false, enabled: {} });

export function defaultEnabled(manifest: CplugManifest): boolean {
  if (manifest.tier === 'dev') return false; //  hidden 
  if (manifest.tier === 'core' || manifest.default_enabled === true) return true;
  if (manifest.default_enabled === false) return false;
  return (manifest.permissions?.app ?? []).every((p) => DEFAULT_GRANTED.has(p));
}

export function cplugEnabled(manifest: CplugManifest): boolean {
  const known = cplugEnablement.enabled[manifest.id];
  return known ?? defaultEnabled(manifest);
}

export async function refreshEnablement(): Promise<void> {
  try {
    const body = await authFetch<{ cplugs: { id: string; enabled: boolean; state?: string }[] }>('/cplugs');
    const next: Record<string, boolean> = {};
    for (const row of Array.isArray(body.cplugs) ? body.cplugs : []) {
      if (row.state !== 'removed') next[row.id] = row.enabled === true;
    }
    cplugEnablement.enabled = next;
    cplugEnablement.read = true;
  } catch {
  }
}

let following = false;

export function followEnablement(changed: () => void = () => {}): void {
  if (following) return;
  following = true;
  const read = (): void => void refreshEnablement().then(changed);
  const push = resourcePush();
  push.onChange((topics) => {
    if (topics.includes(CPLUGS_TOPIC)) read();
  });
  push.pushOrPoll(read, POLL_MS, [CPLUGS_TOPIC]);
  read();
}
