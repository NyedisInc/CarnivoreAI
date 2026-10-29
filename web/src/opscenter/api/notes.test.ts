import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

class FakeApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly payload: unknown;

  constructor(message: string, status: number, code: string | null = null, payload: unknown = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.payload = payload;
  }
}

const calls: Array<{ path: string; method: string; body: unknown }> = [];

let answers: Array<unknown> = [];

vi.mock('./auth.svelte', () => ({
  ApiError: FakeApiError,
  authFetch: (path: string, init: RequestInit = {}) => {
    calls.push({
      path,
      method: (init.method ?? 'GET').toUpperCase(),
      body: typeof init.body === 'string' ? JSON.parse(init.body) : null,
    });
    const answer = answers.shift();
    if (answer instanceof Error) return Promise.reject(answer);
    return Promise.resolve(answer);
  },
}));

let onFrame: ((frame: unknown) => void) | null = null;

vi.mock('./events.svelte', () => ({
  subscribe: (_kind: string, handler: (frame: unknown) => void) => {
    onFrame = handler;
    return () => {
      onFrame = null;
    };
  },
}));

/** A server answer shaped like the endpoint's. */
function answer(body: string, revision: number, status = 'committed') {
  return { status, body, revision, updated_at: '2026-09-20T12:00:00+00:00' };
}

interface Notes {
  AUTOSAVE_MS: number;
  note: import('./note-store.svelte').NoteState;
  open(name: string): Promise<void>;
  edit(text: string): void;
  save(): Promise<void>;
  flush(): Promise<void>;
  keepTheirs(): void;
  keepMine(): Promise<void>;
  reset(): void;
}

async function load(): Promise<Notes> {
  vi.resetModules();
  calls.length = 0;
  answers = [];
  onFrame = null;
  const { NoteStore, AUTOSAVE_MS } = await import('./note-store.svelte');
  const store = new NoteStore();
  return {
    AUTOSAVE_MS,
    note: store.note,
    open: (name) => store.open(name),
    edit: (text) => store.edit(text),
    save: () => store.save(),
    flush: () => store.flush(),
    keepTheirs: () => store.keepTheirs(),
    keepMine: () => store.keepMine(),
    reset: () => store.reset(),
  };
}

describe('reading one session note', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('reads the note and holds the revision it came at', async () => {
    const notes = await load();
    answers = [answer('# todo', 3, 'unchanged')];

    await notes.open('cloude_api');

    expect(calls[0]?.path).toBe('/sessions/cloude_api/note');
    expect(calls[0]?.method).toBe('GET');
    expect(notes.note.body).toBe('# todo');
    expect(notes.note.revision).toBe(3);
    expect(notes.note.load).toBe('loaded');
    expect(notes.note.dirty).toBe(false);
  });

  it('escapes a session name that has a space in it', async () => {
    const notes = await load();
    answers = [answer('', 0, 'unchanged')];
    await notes.open('cloude_Lantern App');
    expect(calls[0]?.path).toBe('/sessions/cloude_Lantern%20App/note');
  });

  it('tells a missing row apart from a failed read', async () => {
    const notes = await load();
    answers = [new FakeApiError('no such session', 404)];
    await notes.open('cloude_gone');
    expect(notes.note.load).toBe('no-note-row');

    answers = [new FakeApiError('server said no', 500)];
    await notes.open('cloude_other');
    expect(notes.note.load).toBe('failed');
  });

  it('is "no session" with no name, and reads nothing', async () => {
    const notes = await load();
    await notes.open('');
    expect(notes.note.load).toBe('no-session');
    expect(calls).toEqual([]);
  });
});

describe('saving', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  async function opened(notes: Notes, body = 'start', revision = 1) {
    answers = [answer(body, revision, 'unchanged')];
    await notes.open('cloude_api');
    calls.length = 0;
  }

  it('waits for the typing to stop before it writes', async () => {
    const notes = await load();
    await opened(notes);

    notes.edit('a');
    notes.edit('ab');
    expect(calls).toEqual([]);

    answers = [answer('ab', 2)];
    await vi.advanceTimersByTimeAsync(notes.AUTOSAVE_MS);

    expect(calls).toHaveLength(1);
    expect(calls[0]?.method).toBe('PUT');
    expect(calls[0]?.body).toEqual({ body: 'ab', expected_revision: 1 });
    expect(notes.note.revision).toBe(2);
    expect(notes.note.save).toBe('saved');
    expect(notes.note.dirty).toBe(false);
  });

  it('sends the revision it holds, never a guess', async () => {
    const notes = await load();
    await opened(notes, 'start', 7);
    notes.edit('mine');
    answers = [answer('mine', 8)];
    await notes.save();
    expect(calls[0]?.body).toEqual({ body: 'mine', expected_revision: 7 });
  });

  it('saves nothing when nothing was typed', async () => {
    const notes = await load();
    await opened(notes);
    await notes.save();
    expect(calls).toEqual([]);
  });

  it('keeps a keystroke made while the write was in flight', async () => {
    const notes = await load();
    await opened(notes);
    notes.edit('one');

    let release: (value: unknown) => void = () => {};
    answers = [new Promise((resolve) => { release = resolve; })];
    const writing = notes.save();
    notes.edit('one two');
    release(answer('one', 2));
    await writing;

    expect(notes.note.body).toBe('one two');
    expect(notes.note.dirty).toBe(true);
    expect(notes.note.revision).toBe(2);
  });

  it('names a note that is too large rather than calling it a failure', async () => {
    const notes = await load();
    await opened(notes);
    notes.edit('enormous');
    answers = [new FakeApiError('too large', 413, null, { detail: { detail: 'too large' } })];
    await notes.save();
    expect(notes.note.save).toBe('too_large');
  });
});

describe('the conflict', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  async function refused(notes: Notes) {
    answers = [answer('theirs base', 1, 'unchanged')];
    await notes.open('cloude_api');
    calls.length = 0;
    notes.edit('mine');
    answers = [
      new FakeApiError('stale', 409, null, {
        detail: { status: 'stale_revision', revision: 4, body: 'theirs', updated_at: null, detail: 'another computer saved first' },
      }),
    ];
    await notes.save();
  }

  it('offers both texts and drops neither', async () => {
    const notes = await load();
    await refused(notes);

    expect(notes.note.save).toBe('conflict');
    expect(notes.note.body).toBe('mine');
    expect(notes.note.conflict).toEqual({ revision: 4, body: 'theirs' });
  });

  it('takes their note when asked, at their revision', async () => {
    const notes = await load();
    await refused(notes);
    notes.keepTheirs();
    expect(notes.note.body).toBe('theirs');
    expect(notes.note.revision).toBe(4);
    expect(notes.note.conflict).toBeNull();
    expect(notes.note.dirty).toBe(false);
  });

  it('overwrites from their revision when asked, so the write can land', async () => {
    const notes = await load();
    await refused(notes);
    calls.length = 0;
    answers = [answer('mine', 5)];

    await notes.keepMine();

    expect(calls[0]?.body).toEqual({ body: 'mine', expected_revision: 4 });
    expect(notes.note.revision).toBe(5);
    expect(notes.note.save).toBe('saved');
    expect(notes.note.conflict).toBeNull();
  });

  it('keeps both texts on screen while the user carries on typing, and sends nothing', async () => {
    const notes = await load();
    await refused(notes);
    calls.length = 0;

    notes.edit('mine, continued');
    await vi.advanceTimersByTimeAsync(notes.AUTOSAVE_MS * 2);

    expect(notes.note.body).toBe('mine, continued');
    expect(notes.note.conflict).toEqual({ revision: 4, body: 'theirs' });
    expect(notes.note.save).toBe('conflict');
    expect(calls).toEqual([]);
  });

  it('saves the text as it now stands when the overwrite is pressed', async () => {
    const notes = await load();
    await refused(notes);
    notes.edit('mine, continued');
    calls.length = 0;
    answers = [answer('mine, continued', 5)];

    await notes.keepMine();

    expect(calls[0]?.body).toEqual({ body: 'mine, continued', expected_revision: 4 });
    expect(notes.note.save).toBe('saved');
  });
});

describe('the change frame', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  async function opened(notes: Notes) {
    answers = [answer('theirs', 2, 'unchanged')];
    await notes.open('cloude_api');
    calls.length = 0;
  }

  it('re-reads on a strictly higher revision for this session', async () => {
    const notes = await load();
    await opened(notes);
    answers = [answer('newer', 3, 'unchanged')];

    onFrame?.({ type: 'session.note.changed', tmux_session: 'cloude_api', revision: 3 });
    await vi.advanceTimersByTimeAsync(0);

    expect(calls).toHaveLength(1);
    expect(notes.note.body).toBe('newer');
    expect(notes.note.revision).toBe(3);
  });

  it('ignores a frame at or below the revision it already holds', async () => {
    const notes = await load();
    await opened(notes);

    onFrame?.({ type: 'session.note.changed', tmux_session: 'cloude_api', revision: 2 });
    onFrame?.({ type: 'session.note.changed', tmux_session: 'cloude_api', revision: 1 });
    await vi.advanceTimersByTimeAsync(0);

    expect(calls).toEqual([]);
  });

  it('ignores a frame about another session', async () => {
    const notes = await load();
    await opened(notes);
    onFrame?.({ type: 'session.note.changed', tmux_session: 'cloude_other', revision: 9 });
    await vi.advanceTimersByTimeAsync(0);
    expect(calls).toEqual([]);
  });

  it('never repaints a box that has an unsaved edit in it', async () => {
    const notes = await load();
    await opened(notes);
    notes.edit('half a thought');
    calls.length = 0;

    onFrame?.({ type: 'session.note.changed', tmux_session: 'cloude_api', revision: 9 });
    await vi.advanceTimersByTimeAsync(0);

    expect(notes.note.body).toBe('half a thought');
    expect(calls).toEqual([]);
  });
});

describe('what the note is never allowed to touch', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
    delete (globalThis as { localStorage?: unknown }).localStorage;
  });

  it('puts no note body in browser storage, by any route', async () => {
    const written: string[] = [];
    (globalThis as { localStorage?: unknown }).localStorage = {
      getItem: () => null,
      setItem: (_key: string, value: string) => void written.push(value),
      removeItem: () => {},
    };

    const notes = await load();
    answers = [answer('a secret note', 1, 'unchanged')];
    await notes.open('cloude_api');
    notes.edit('a secret note, edited');
    answers = [answer('a secret note, edited', 2)];
    await vi.advanceTimersByTimeAsync(notes.AUTOSAVE_MS);

    expect(written).toEqual([]);
  });

  it('discards an answer about a session the page has left', async () => {
    const notes = await load();
    let release: (value: unknown) => void = () => {};
    answers = [new Promise((resolve) => { release = resolve; })];
    const first = notes.open('cloude_one');

    answers.push(answer('second', 5, 'unchanged'));
    const second = notes.open('cloude_two');
    release(answer('first', 9));
    await first;
    await second;

    expect(notes.note.name).toBe('cloude_two');
    expect(notes.note.body).toBe('second');
    expect(notes.note.revision).toBe(5);
  });
});

describe('switching sessions with a failed save (H26)', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('keeps the edit whose save failed and gives it back when that session is opened again', async () => {
    const notes = await load();
    answers = [answer('start', 1, 'unchanged')];
    await notes.open('cloude_one');
    notes.edit('typed words');
    answers = [new FakeApiError('server said no', 500), answer('other', 1, 'unchanged')];
    await notes.open('cloude_two');
    expect(notes.note.body).toBe('other');

    answers = [answer('start', 1, 'unchanged')];
    await notes.open('cloude_one');
    expect(notes.note.body).toBe('typed words');
    expect(notes.note.dirty).toBe(true);
  });

  it('offers the server note beside the kept edit when the server moved on', async () => {
    const notes = await load();
    answers = [answer('start', 1, 'unchanged')];
    await notes.open('cloude_one');
    notes.edit('typed words');
    answers = [new FakeApiError('server said no', 500), answer('other', 1, 'unchanged')];
    await notes.open('cloude_two');
    answers = [answer('newer', 4, 'unchanged')];
    await notes.open('cloude_one');
    expect(notes.note.body).toBe('typed words');
    expect(notes.note.conflict).toEqual({ revision: 4, body: 'newer' });
  });
});

describe('the last widget letting go of a dirty store (H26 across the registry)', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  async function registry() {
    vi.resetModules();
    calls.length = 0;
    answers = [];
    onFrame = null;
    return import('./notes.svelte');
  }

  it('hands a failed edit to the unsaved map, and the next widget on that session is given it back', async () => {
    const registryModule = await registry();
    answers = [answer('start', 1, 'unchanged')];
    const store = registryModule.acquire('cloude_one');
    await vi.advanceTimersByTimeAsync(0);
    store.edit('typed words');
    answers = [new FakeApiError('server said no', 500)];
    await registryModule.release('cloude_one');

    answers = [answer('start', 1, 'unchanged')];
    const again = registryModule.acquire('cloude_one');
    await vi.advanceTimersByTimeAsync(0);
    expect(again).not.toBe(store);
    expect(again.note.body).toBe('typed words');
    expect(again.note.dirty).toBe(true);
    registryModule.reset();
  });
});
