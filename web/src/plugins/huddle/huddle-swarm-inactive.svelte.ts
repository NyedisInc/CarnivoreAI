
export const SWARM_INACTIVE_KEY = 'cloude.huddle.swarmInactive';

function load(): boolean {
  try {
    return globalThis.localStorage?.getItem(SWARM_INACTIVE_KEY) === 'shown';
  } catch {
    return false;
  }
}

export const swarmInactive = $state<{ shown: boolean }>({ shown: load() });

export function setSwarmInactive(shown: boolean): void {
  swarmInactive.shown = shown;
  try {
    globalThis.localStorage?.setItem(SWARM_INACTIVE_KEY, shown ? 'shown' : 'hidden');
  } catch {
  }
}
