import { afterEach, describe, expect, test, vi } from 'vitest';

const made = vi.hoisted(() => ({ calls: [] as Array<{ topics?: readonly string[]; name: string }>, stop: vi.fn() }));
vi.mock('./poll.svelte', () => ({
  resource: (_fetch: unknown, options: { topics?: readonly string[]; name: string }) => {
    made.calls.push(options);
    return { stop: made.stop, data: null, status: 'loading' };
  },
}));
vi.mock('./auth.svelte', () => ({ authFetch: vi.fn() }));

import { releaseSessionTimeline, sessionTimeline, SESSION_TIMELINE_TOPIC } from './session-timeline.svelte';

afterEach(() => { made.calls.length = 0; made.stop.mockClear(); });

describe('the timeline read', () => {
  test('is re-read on the timeline topic and on that session\'s bookmarks, and shared by reference count', () => {
    const a = sessionTimeline(7);
    const b = sessionTimeline(7);
    expect(a).toBe(b);
    expect(made.calls).toHaveLength(1);
    expect(made.calls[0]!.topics).toEqual([SESSION_TIMELINE_TOPIC, 'bookmarks:7']);
    expect(SESSION_TIMELINE_TOPIC).toBe('session_timeline');
    releaseSessionTimeline(7);
    expect(made.stop).not.toHaveBeenCalled();
    releaseSessionTimeline(7);
    expect(made.stop).toHaveBeenCalledTimes(1);
  });
});
