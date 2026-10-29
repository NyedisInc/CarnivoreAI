/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import Notes from './Notes.svelte';
import { AdminApi, type Fetcher } from './admin.js';
import { createNotesHost, type NotesHost } from './notes-host.svelte.js';
import type { NoteRow } from './notes.js';

/** One recorded request. */
interface Call {
    url: string;
    method: string;
    headers: Record<string, string>;
}

/** A fake fetch answering by path, recording every call. */
function routed(answers: Record<string, { status: number; body: unknown }>): {
    fetcher: Fetcher;
    calls: Call[];
} {
    const calls: Call[] = [];
    const fetcher: Fetcher = async (url, init) => {
        const method = init?.method || 'GET';
        calls.push({ url, method, headers: init?.headers || {} });
        const answer = answers[method + ' ' + url];
        if (!answer) throw new Error('unscripted request: ' + method + ' ' + url);
        return {
            ok: answer.status >= 200 && answer.status < 300,
            status: answer.status,
            json: async () => answer.body,
        };
    };
    return { fetcher, calls };
}

const NOTE: NoteRow = {
    note_id: 'ab12cd34ef56ab12cd34ef56ab12cd34',
    item_id: 'bundled/matrix',
    text: 'the background is too bright on the argent variant.\nplease darken it a shade.',
    sender_id: 'cognito:11111111-2222-3333-4444-555555555555',
    sender_login: 'a-theme-reader',
    created_at: '2026-09-20T10:00:00Z',
    status: 'unread',
    read_at: null,
};

async function paint(answers: Record<string, { status: number; body: unknown }>) {
    const { fetcher, calls } = routed(answers);
    const api = new AdminApi(fetcher, () => 'ACCESS-TOKEN');
    let signedOut = false;
    const host: NotesHost = createNotesHost({
        api,
        onUnauthorized: () => {
            signedOut = true;
        },
    });
    await host.loadNotes('unread');
    const target = document.createElement('div');
    document.body.appendChild(target);
    const app = mount(Notes, { target, props: { host } });
    flushSync();
    return { app, target, host, calls, signedOut: () => signedOut };
}

afterEach(() => {
    document.body.innerHTML = '';
});

describe('a note renders as text, never as markup', () => {
    test('markup-looking text survives literally, with no live tag', async () => {
        const markup: NoteRow = {
            ...NOTE,
            note_id: 'ff11ee22dd33ff11ee22dd33ff11ee22',
            text: 'please add a <b>bold</b> accent color',
        };
        const { app, target } = await paint({
            'GET https://api.carnivore.ai/v1/notes?status=unread': {
                status: 200,
                body: { status: 'unread', notes: [markup] },
            },
        });

        expect(target.textContent).toContain('please add a <b>bold</b> accent color');
        expect(target.querySelector('b')).toBe(null);
        expect(target.innerHTML).not.toContain('<b>bold</b>');

        unmount(app);
    });

    test('item id and sender login are not swapped, and the newline shows', async () => {
        const { app, target } = await paint({
            'GET https://api.carnivore.ai/v1/notes?status=unread': {
                status: 200,
                body: { status: 'unread', notes: [NOTE] },
            },
        });

        expect(target.textContent).toContain(NOTE.item_id);
        expect(target.textContent).toContain(NOTE.sender_login);
        expect(target.textContent).not.toContain('from ' + NOTE.item_id);
        expect(target.textContent).toContain('2026-09-20');
        const body = target.querySelector('.admin-note-text');
        expect(body?.textContent).toBe(NOTE.text);

        unmount(app);
    });
});

describe('marking a note', () => {
    test('mark read sends one request and the row leaves the unread list', async () => {
        const { app, target, host, calls } = await paint({
            'GET https://api.carnivore.ai/v1/notes?status=unread': {
                status: 200,
                body: { status: 'unread', notes: [NOTE] },
            },
            'POST https://api.carnivore.ai/v1/notes/ab12cd34ef56ab12cd34ef56ab12cd34/read': {
                status: 200,
                body: { ...NOTE, status: 'read', read_at: '2026-09-22T00:00:00Z' },
            },
        });
        expect(target.textContent).toContain(NOTE.item_id);
        const before = calls.length;

        await host.mark(NOTE.note_id, true);
        flushSync();

        expect(calls).toHaveLength(before + 1);
        const mark = calls.at(-1);
        expect(mark?.method).toBe('POST');
        expect(mark?.url).toBe(
            'https://api.carnivore.ai/v1/notes/ab12cd34ef56ab12cd34ef56ab12cd34/read',
        );
        expect(mark?.headers.authorization).toBe('Bearer ACCESS-TOKEN');
        expect(target.textContent).not.toContain(NOTE.item_id);
        expect(target.textContent).toContain('nothing here');

        unmount(app);
    });
});

describe('the first load, mounted with an unloaded host', () => {
    test('a failing first load issues exactly one request, never a retry loop', async () => {
        const { fetcher, calls } = routed({
            'GET https://api.carnivore.ai/v1/notes?status=unread': {
                status: 503,
                body: { code: 'unavailable' },
            },
        });
        const api = new AdminApi(fetcher, () => 'ACCESS-TOKEN');
        const host: NotesHost = createNotesHost({ api });
        const target = document.createElement('div');
        document.body.appendChild(target);

        const app = mount(Notes, { target, props: { host } });
        flushSync();
        await Promise.resolve();
        flushSync();
        await new Promise((resolve) => setTimeout(resolve, 0));
        flushSync();
        await new Promise((resolve) => setTimeout(resolve, 0));
        flushSync();

        expect(calls).toHaveLength(1);
        expect(host.loaded).toBe(false);
        expect(host.refusal?.code).toBe('unavailable');

        unmount(app);
    });
});

describe('a session whose token has expired', () => {
    test('a 401 signs the caller out rather than leaving a stale list', async () => {
        const { app, signedOut } = await paint({
            'GET https://api.carnivore.ai/v1/notes?status=unread': {
                status: 401,
                body: { code: 'unauthorized' },
            },
        });
        expect(signedOut()).toBe(true);

        unmount(app);
    });
});

describe('signing out', () => {
    test('reset clears loaded rows so a second admin on the tab sees none of them', async () => {
        const { fetcher } = routed({
            'GET https://api.carnivore.ai/v1/notes?status=unread': {
                status: 200,
                body: { status: 'unread', notes: [NOTE] },
            },
        });
        const api = new AdminApi(fetcher, () => 'ACCESS-TOKEN');
        const host: NotesHost = createNotesHost({ api });
        await host.loadNotes('unread');
        expect(host.notes).toHaveLength(1);
        expect(host.loaded).toBe(true);

        host.reset();

        expect(host.notes).toHaveLength(0);
        expect(host.loaded).toBe(false);
        expect(host.status).toBe('unread');
        expect(host.refusal).toBe(null);
    });
});
