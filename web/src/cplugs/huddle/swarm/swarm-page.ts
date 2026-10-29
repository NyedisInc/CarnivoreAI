export const SWARM_PAGE = 'huddle.pack';
export const SWARM_HASH = '#swarm';
export const SWARM_TAB_KEY = 'swarm';
export const SWARM_TABS = ['tree', 'org', 'squares', 'board'] as const;
export type SwarmTab = (typeof SWARM_TABS)[number];
