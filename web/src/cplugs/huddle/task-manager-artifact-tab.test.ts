import { afterEach, describe, expect, it, vi } from 'vitest';

const openPage = vi.hoisted(() => vi.fn(async () => ({})));
vi.mock('../sdk', async (original) => ({ ...(await original<Record<string, unknown>>()), openPage }));

import { registerPostedPageOpener, resetPostedPageOpener } from '../sdk/artifact-opener';
import { openArtifactInTab } from './task-manager-artifact.svelte';

const artifact = { id: '0a1b2c3d', title: 'Layout A', description: '', size: 10 };

afterEach(() => {
  resetPostedPageOpener();
  vi.clearAllMocks();
});

describe('open in tab', () => {
  it('opens the stored artifact when no plugin registered an opener', async () => {
    expect(await openArtifactInTab(7, artifact)).toBe(true);
    expect(openPage).toHaveBeenCalledWith({ huddle_artifact: { item: 7, artifact: '0a1b2c3d' }, title: 'Layout A' });
  });

  it('opens the board and not the artifact when the opener finds one', async () => {
    const opener = vi.fn(async () => true);
    registerPostedPageOpener(opener);
    expect(await openArtifactInTab(7, artifact)).toBe(true);
    expect(opener).toHaveBeenCalledWith({ item: 7, title: 'Layout A' });
    expect(openPage).not.toHaveBeenCalled();
  });

  it('falls back to the stored artifact when the task has no such board, or the opener fails', async () => {
    registerPostedPageOpener(async () => false);
    await openArtifactInTab(7, artifact);
    registerPostedPageOpener(async () => { throw new Error('refused'); });
    await openArtifactInTab(7, artifact);
    expect(openPage).toHaveBeenCalledTimes(2);
  });
});
