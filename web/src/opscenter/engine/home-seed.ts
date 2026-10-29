
export const FIRST_SEED_MARKER = 'cloudecode.opscenter.home-analytics.v1';
export const FULL_SEED_MARKER = 'cloudecode.opscenter.home-analytics.v2';

let serverLevel: number | null = null;
let wanted = 0;
let onWanted: (() => void) | null = null;
let ready: Promise<void> = Promise.resolve();
let readyResolve: (() => void) | null = null;

export function localSeedLevel(): number {
  try {
    if (localStorage.getItem(FULL_SEED_MARKER) === 'done') return 2;
    if (localStorage.getItem(FIRST_SEED_MARKER) === 'done') return 1;
  } catch {
  }
  return 0;
}

export function cacheSeedLevel(level: number): void {
  try {
    if (level >= 1) localStorage.setItem(FIRST_SEED_MARKER, 'done');
    if (level >= 2) localStorage.setItem(FULL_SEED_MARKER, 'done');
  } catch {
  }
}

export function homeSeedLevel(): number {
  return Math.max(serverLevel ?? localSeedLevel(), wanted);
}

export function setHomeSeedLevel(level: number): void {
  if (level <= homeSeedLevel()) return;
  cacheSeedLevel(level);
  if (!onWanted) return;
  wanted = level;
  onWanted();
}

let referencedIds: (() => Set<string>) | null = null;

export function homeReferencedAnalytics(): Set<string> | null {
  return referencedIds ? referencedIds() : null;
}

export function whenHomeSyncReady(): Promise<void> {
  return ready;
}

export const seedControl = {
  attach(notify: () => void, referenced?: () => Set<string>): void {
    onWanted = notify;
    referencedIds = referenced ?? null;
    ready = new Promise<void>((resolve) => {
      readyResolve = resolve;
    });
  },
  setServer(level: number | null): void {
    serverLevel = level;
    if (level !== null && level >= wanted) wanted = 0;
  },
  pending(): number {
    return wanted;
  },
  markReady(): void {
    readyResolve?.();
    readyResolve = null;
  },
  reset(): void {
    onWanted = null;
    referencedIds = null;
    serverLevel = null;
    wanted = 0;
    seedControl.markReady();
    ready = Promise.resolve();
  },
};
