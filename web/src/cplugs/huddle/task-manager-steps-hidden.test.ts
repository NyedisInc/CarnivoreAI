/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';

const rig = vi.hoisted(() => ({
  reads: 0,
  listeners: new Set<(topics: string[]) => void>(),
  name(topics: string[]) {
    for (const listener of [...this.listeners]) listener(topics);
  },
}));

vi.mock('../sdk', async (importOriginal) => {
  const real = await importOriginal<typeof import('../sdk')>();
  return {
    ...real,
    authFetch: async (path: string) => {
      if (path === '/cplugs/huddle/steps') rig.reads += 1;
      return { lists: {} };
    },
    resourcePush: () => ({
      onChange(listener: (topics: string[]) => void) {
        rig.listeners.add(listener);
        return () => rig.listeners.delete(listener);
      },
    }),
  };
});

import { STEPS_TOPIC, holdSteps, releaseSteps } from './task-manager-steps.svelte';

function setVisibility(state: 'hidden' | 'visible'): void {
  Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => state });
  document.dispatchEvent(new Event('visibilitychange'));
}

const settle = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0));

afterEach(() => {
  releaseSteps();
  setVisibility('visible');
});

describe('steps strip visibility', () => {
  test('a hidden tab reads nothing across three keepalives and once when shown', async () => {
    holdSteps();
    await settle();
    expect(rig.reads).toBe(1);
    setVisibility('hidden');
    rig.reads = 0;
    for (let tick = 0; tick < 3; tick += 1) {
      rig.name([STEPS_TOPIC]);
      await settle();
    }
    console.info(`hidden tab, 3 keepalives: ${rig.reads} steps reads (before: 3)`);
    expect(rig.reads).toBe(0);
    setVisibility('visible');
    await settle();
    expect(rig.reads).toBe(1);

    rig.name([STEPS_TOPIC]);
    await settle();
    expect(rig.reads).toBe(2);
    setVisibility('hidden');
    setVisibility('visible');
    await settle();
    expect(rig.reads).toBe(2);
  });
});
