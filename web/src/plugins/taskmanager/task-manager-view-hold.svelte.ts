import type { ViewHoldSnapshot } from './task-manager-view-hold';

export const HOLD_LEAVE_MS = 800;
export const HOLD_IDLE_MS = 30_000;
export const HOLD_SUSPEND_MS = 2_500;

export interface ViewHold {
  readonly snapshot: ViewHoldSnapshot | null;
  look(take: () => ViewHoldSnapshot, pointer?: boolean): void;
  leave(): void;
  act(): void;
  release(): void;
}

export function createViewHold(now: () => number = Date.now): ViewHold {
  let snapshot = $state.raw<ViewHoldSnapshot | null>(null);
  let suspendedUntil = 0;
  let pointerInside = false;
  let leaveTimer: ReturnType<typeof setTimeout> | undefined;
  let idleTimer: ReturnType<typeof setTimeout> | undefined;

  const clear = (): void => { clearTimeout(leaveTimer); clearTimeout(idleTimer); leaveTimer = idleTimer = undefined; };
  const release = (): void => { clear(); snapshot = null; pointerInside = false; };
  const idleEnd = (): void => { if (!pointerInside) release(); };

  return {
    get snapshot() { return snapshot; },
    look(take, pointer = false) {
      clearTimeout(leaveTimer);
      if (pointer) pointerInside = true;
      if (snapshot === null) {
        if (now() < suspendedUntil) return;
        snapshot = take();
      }
      clearTimeout(idleTimer);
      idleTimer = setTimeout(idleEnd, HOLD_IDLE_MS);
    },
    leave() {
      clearTimeout(leaveTimer);
      pointerInside = false;
      if (snapshot !== null) leaveTimer = setTimeout(release, HOLD_LEAVE_MS);
    },
    act() {
      release();
      suspendedUntil = now() + HOLD_SUSPEND_MS;
    },
    release,
  };
}
