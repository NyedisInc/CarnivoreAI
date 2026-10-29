
import { startAutoSleepFrames } from './auto-sleep-toast';
import { announceChanges, isKeptAwake, setKeepAwake } from './auto-sleep-store.svelte';

export const autoSleepBridge = {
  isKeptAwake,
  setKeepAwake,
};

export function startAutoSleep(): void {
  startAutoSleepFrames();
  announceChanges();
}
