
export const SWARM_VIEW_KEY = 'cloude.huddle.swarmView';

export type SwarmView = 'swarm' | 'lists';

function load(): SwarmView {
  try {
    return globalThis.localStorage?.getItem(SWARM_VIEW_KEY) === 'lists' ? 'lists' : 'swarm';
  } catch {
    return 'swarm';
  }
}

export const swarmView = $state<{ view: SwarmView }>({ view: load() });

export function setSwarmView(view: SwarmView): void {
  swarmView.view = view;
  try {
    globalThis.localStorage?.setItem(SWARM_VIEW_KEY, view);
  } catch {
  }
}
