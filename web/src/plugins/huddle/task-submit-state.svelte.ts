import { untrack } from 'svelte';

export const SENT_FLASH_MS = 1200;

export type SubmitLook = 'idle' | 'ready' | 'sent';

export function submitLook(hasText: boolean, flashing: boolean): SubmitLook {
  if (flashing) return 'sent';
  return hasText ? 'ready' : 'idle';
}

export function createSentFlash(ms: number = SENT_FLASH_MS): { readonly on: boolean; flash: () => void; stop: () => void } {
  let on = $state(false);
  let timer: ReturnType<typeof setTimeout> | null = null;
  const stop = (): void => {
    if (timer !== null) clearTimeout(timer);
    timer = null;
    untrack(() => { on = false; });
  };
  return {
    get on() { return on; },
    flash() {
      if (timer !== null) clearTimeout(timer);
      on = true;
      timer = setTimeout(stop, ms);
    },
    stop,
  };
}
