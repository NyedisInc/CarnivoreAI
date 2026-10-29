import { beforeEach, expect, test, vi } from 'vitest';

const push = vi.hoisted(() => ({ stop: vi.fn(), pushOrPoll: vi.fn() }));
vi.mock('./boot', () => ({ resourcePush: () => ({ pushOrPoll: push.pushOrPoll }) }));
import { createPushedStore } from './pushed-store';

beforeEach(() => {
    push.stop.mockReset();
    push.pushOrPoll.mockReset().mockReturnValue(push.stop);
});

test('the first attach subscribes once, the last detach stops it, clears the fetcher and runs onDetach', async () => {
    const read = vi.fn(async () => {});
    const onDetach = vi.fn();
    const store = createPushedStore<string>({ topics: ['t'], pollMs: 99, read, onDetach });
    const a = store.attach('seam');
    const b = store.attach();
    expect(push.pushOrPoll).toHaveBeenCalledTimes(1);
    expect(push.pushOrPoll.mock.calls[0]![1]).toBe(99);
    expect(push.pushOrPoll.mock.calls[0]![2]).toEqual(['t']);
    expect(store.fetcher()).toBe('seam');
    expect(read).toHaveBeenCalledWith('seam');
    a();
    expect(push.stop).not.toHaveBeenCalled();
    b();
    expect(push.stop).toHaveBeenCalledTimes(1);
    expect(store.fetcher()).toBeUndefined();
    expect(onDetach).toHaveBeenCalledTimes(1);
});

test('a refresh asked during a read waits for one trailing read that starts after the call', async () => {
    let release!: () => void;
    let calls = 0;
    const read = vi.fn(() => { calls += 1; return calls === 1 ? new Promise<void>((r) => { release = r; }) : Promise.resolve(); });
    const store = createPushedStore<string>({ topics: ['t'], pollMs: 1, read });
    const first = store.refresh();
    const second = store.refresh();
    const third = store.refresh();
    expect(read).toHaveBeenCalledTimes(1);
    release();
    await Promise.all([first, second, third]);
    expect(read).toHaveBeenCalledTimes(2);
});
