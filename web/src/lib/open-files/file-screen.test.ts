/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { flushSync, tick } from 'svelte';

const server = vi.hoisted(() => {
    localStorage.setItem('claude_tunnel_token', 'an-access-token');
    return {
        files: [] as Record<string, unknown>[],
        contents: {} as Record<string, Record<string, unknown>>,
        disk: {} as Record<string, string>,
        puts: [] as Array<{ id: string; body: Record<string, unknown> }>,
        posts: [] as Record<string, unknown>[],
        deletes: [] as string[],
        reads: [] as string[],
    };
});

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
    const real = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
    return {
        ...real,
        authFetch: async (p: string, init: RequestInit = {}) => {
            const method = init.method ?? 'GET';
            if (p === '/browsers/pages') return { pages: [] };
            if (p === '/browsers') return { browsers: [] };
            if (p === '/files/open' && method === 'GET') return { files: server.files.map((f) => ({ ...f })) };
            if (p === '/files/open' && method === 'POST') {
                const body = JSON.parse(String(init.body));
                server.posts.push(body);
                const row = { id: 'c1b2c3d4e5f60718', kind: body.kind, root: body.root, path: body.path, session_uuid: body.session_uuid,
                    title: String(body.path).split('/').pop(), opened_at: 9, seq: 9 };
                server.files.push(row);
                server.contents[row.id] = { id: row.id, viewable: true, content: 'opened\n', sha256: 's-open' };
                server.disk[row.id] = 's-open';
                return { file: row, reused: false };
            }
            const content = /^\/files\/open\/([0-9a-f]{16})\/content$/.exec(p);
            if (content && method === 'GET') {
                server.reads.push(content[1]!);
                return { ...server.contents[content[1]!] };
            }
            if (content && method === 'PUT') {
                const id = content[1]!;
                const body = JSON.parse(String(init.body));
                server.puts.push({ id, body });
                if (!body.overwrite && body.expected_sha256 !== server.disk[id]) {
                    throw new real.ApiError('the file changed on disk', 409, null,
                        { detail: { code: 'file_changed_on_disk', detail: 'changed', sha256: server.disk[id] } });
                }
                server.disk[id] = `s-saved-${server.puts.length}`;
                return { id, backed_up: true, is_executable: false, is_sensitive: false, sha256: server.disk[id], mtime_ns: 1 };
            }
            const row = /^\/files\/open\/([0-9a-f]{16})$/.exec(p);
            if (row && method === 'DELETE') {
                server.deletes.push(row[1]!);
                server.files = server.files.filter((f) => f.id !== row[1]);
                return undefined;
            }
            if (p === '/sessions/records') return [{ id: 3, session_uuid: 'u-1', tmux_name: 'carnivore_a' }];
            if (p === '/sessions/list') return [{ session_row_id: 3, session: { id: 'ses_1' } }];
            if (p.startsWith('/sessions/ses_1/git-diff')) return { state: 'ok', path: 'README.md', text: '+added line', binary: false };
            return {};
        },
    };
});
vi.mock('../browser/browser-socket', () => ({ openBrowserSocket: () => ({ send: () => {}, reopen: () => {}, close: () => {} }) }));
vi.mock('../browser/pop-out', () => ({ popOutItem: async () => true }));
vi.mock('./codemirror', () => ({
    loadCodeMirror: async () => ({
        createEditor: (host: HTMLElement, content: string, _path: string, readOnly: boolean, onChange: (v: string) => void) => {
            const area = document.createElement('textarea');
            area.value = content;
            area.readOnly = readOnly;
            area.addEventListener('input', () => onChange(area.value));
            host.appendChild(area);
            return { getValue: () => area.value, setContent: () => {}, setReadOnly: () => {}, focus: () => {}, destroy: () => area.remove() };
        },
    }),
}));

import { browserBridge, closeBrowserScreen, dismissBrowserScreen, openBrowser } from '../browser/screen-host';
import { openFiles } from './api.svelte';
import { dropBuffer, isDirty } from './buffers.svelte';
import { openFromDrawer } from './open-bridge';

const FILE = { id: 'a1b2c3d4e5f60718', kind: 'file', root: 'workdir', path: 'src/main.py', session_uuid: 'u-1', title: 'main.py', opened_at: 1, seq: 1 };
const BIN = { ...FILE, id: 'b1b2c3d4e5f60718', path: 'logo.png', title: 'logo.png' };
const DIFF = { ...FILE, id: 'd1b2c3d4e5f60718', kind: 'diff', path: 'README.md', title: 'README.md' };

async function settle(): Promise<void> {
    for (let i = 0; i < 12; i += 1) { await Promise.resolve(); await tick(); }
    flushSync();
}

const headerCalls: string[] = [];
let confirmAnswer = true;
const confirms: string[] = [];

function q<T extends Element = HTMLElement>(sel: string): T | null {
    return document.querySelector<T>(sel);
}

function type(text: string): void {
    const area = q<HTMLTextAreaElement>('[data-file-editor] textarea')!;
    area.value = text;
    area.dispatchEvent(new Event('input'));
    flushSync();
}

describe('a file in the main section', () => {
    beforeEach(async () => {
        vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} unobserve() {} });
        document.body.innerHTML = '<span id="header-title-text" data-full-title="ses 02c3ff15">ses 02c3ff15</span>'
            + '<span id="header-rename-pencil"></span>'
            + '<div id="terminal-screen" class="screen active"><div id="terminal-grid"><div id="browser-screen"></div></div></div>';
        headerCalls.length = 0;
        confirms.length = 0;
        confirmAnswer = true;
        server.files = [FILE, BIN, DIFF];
        server.contents = {
            [FILE.id]: { id: FILE.id, viewable: true, content: 'print(1)\n', sha256: 's-1', is_executable: false, is_sensitive: false, read_only: false },
            [BIN.id]: { id: BIN.id, viewable: false, reason: 'not_text', detail: 'not utf-8' },
        };
        server.disk = { [FILE.id]: 's-1' };
        server.puts = [];
        server.posts = [];
        server.deletes = [];
        server.reads = [];
        const g = globalThis as Record<string, unknown>;
        g.App = {
            hideAllScreens: () => { document.querySelectorAll('.screen').forEach((el) => el.classList.remove('active')); closeBrowserScreen(); },
            showConfirmModal: async (title: string) => { confirms.push(title); return confirmAnswer; },
        };
        g.setHeaderIdentity = (o: { icon: string; title: string }) => { headerCalls.push(`${o.icon}:${o.title}`); };
        g.setPageTitle = () => {};
        await openFiles.refresh(true);
    });
    afterEach(() => {
        dismissBrowserScreen();
        for (const f of [FILE, BIN, DIFF]) dropBuffer(f.id);
        for (const k of ['App', 'setHeaderIdentity', 'setPageTitle']) delete (globalThis as Record<string, unknown>)[k];
        document.body.innerHTML = '';
        history.replaceState(null, '', '/');
        vi.unstubAllGlobals();
    });

    test('a file row takes the main section, the header names the file, and a dismiss restores it', async () => {
        expect(openBrowser(FILE.id)).toBe(true);
        await settle();
        expect(q('#terminal-grid > #browser-screen .fscreen')).not.toBeNull();
        expect(document.getElementById('terminal-grid')!.hasAttribute('data-center-page')).toBe(true);
        expect(q('.fs-path')?.textContent).toBe('src/main.py');
        expect(headerCalls.at(-1)).toBe('brand:main.py');
        expect(q<HTMLTextAreaElement>('[data-file-editor] textarea')?.value).toBe('print(1)\n');
        expect(dismissBrowserScreen()).toBe(true);
        await settle();
        expect(q('.fscreen')).toBeNull();
        expect(document.getElementById('terminal-grid')!.hasAttribute('data-center-page')).toBe(false);
        expect(headerCalls.at(-1)).toBe('cloude:ses 02c3ff15');
    });

    test('a save names its base; a stale one is refused with reload and overwrite', async () => {
        openBrowser(FILE.id);
        await settle();
        type('print(2)\n');
        expect(isDirty(FILE.id)).toBe(true);
        expect(q('[data-file-dirty]')).not.toBeNull();
        server.disk[FILE.id] = 's-agent';
        q<HTMLButtonElement>('[data-file-save]')!.click();
        await settle();
        expect(server.puts.at(-1)!.body).toMatchObject({ content: 'print(2)\n', expected_sha256: 's-1' });
        expect(q('[data-file-stale]')).not.toBeNull();
        expect(isDirty(FILE.id)).toBe(true);

        q<HTMLButtonElement>('[data-file-overwrite]')!.click();
        await settle();
        expect(server.puts.at(-1)!.body).toMatchObject({ content: 'print(2)\n', overwrite: true });
        expect(server.puts.at(-1)!.body.expected_sha256).toBeUndefined();
        expect(q('[data-file-stale]')).toBeNull();
        expect(isDirty(FILE.id)).toBe(false);
        expect(q('.fs-msg')?.textContent).toContain('saved');
    });

    test('reload from disk replaces the edits with the file as it is now', async () => {
        openBrowser(FILE.id);
        await settle();
        type('mine\n');
        server.disk[FILE.id] = 's-agent';
        server.contents[FILE.id] = { ...server.contents[FILE.id], content: 'theirs\n', sha256: 's-agent' };
        q<HTMLButtonElement>('[data-file-save]')!.click();
        await settle();
        q<HTMLButtonElement>('[data-file-reload]')!.click();
        await settle();
        expect(q('[data-file-stale]')).toBeNull();
        expect(isDirty(FILE.id)).toBe(false);
        expect(q<HTMLTextAreaElement>('[data-file-editor] textarea')?.value).toBe('theirs\n');
        type('theirs and mine\n');
        q<HTMLButtonElement>('[data-file-save]')!.click();
        await settle();
        expect(server.puts.at(-1)!.body).toMatchObject({ expected_sha256: 's-agent' });
        expect(q('[data-file-stale]')).toBeNull();
    });

    test('a file deleted on disk keeps the edits: no reload, overwrite saves it again', async () => {
        openBrowser(FILE.id);
        await settle();
        type('mine\n');
        server.disk[FILE.id] = 's-agent';
        q<HTMLButtonElement>('[data-file-save]')!.click();
        await settle();
        server.contents[FILE.id] = { id: FILE.id, viewable: false, reason: 'gone', detail: 'not a file' };
        q<HTMLButtonElement>('[data-file-reload]')!.click();
        await settle();
        expect(q('[data-file-cant]')).toBeNull();
        expect(q<HTMLTextAreaElement>('[data-file-editor] textarea')?.value).toBe('mine\n');
        expect(isDirty(FILE.id)).toBe(true);
        expect(q('[data-file-stale]')?.textContent).toContain('deleted on disk');
        expect(q('[data-file-reload]')).toBeNull();
        q<HTMLButtonElement>('[data-file-overwrite]')!.click();
        await settle();
        expect(server.puts.at(-1)!.body).toMatchObject({ content: 'mine\n', overwrite: true });
        expect(isDirty(FILE.id)).toBe(false);
    });

    test('a save refused because the file is gone says so from the start', async () => {
        openBrowser(FILE.id);
        await settle();
        type('mine\n');
        server.disk[FILE.id] = null as unknown as string;
        q<HTMLButtonElement>('[data-file-save]')!.click();
        await settle();
        expect(q('[data-file-stale]')?.textContent).toContain('deleted on disk');
        expect(q('[data-file-reload]')).toBeNull();
        expect(q('[data-file-overwrite]')).not.toBeNull();
    });

    test('Cmd+S saves from anywhere in the screen', async () => {
        openBrowser(FILE.id);
        await settle();
        type('print(3)\n');
        q('.fscreen')!.dispatchEvent(new KeyboardEvent('keydown', { key: 's', metaKey: true, bubbles: true }));
        await settle();
        expect(server.puts).toHaveLength(1);
        expect(isDirty(FILE.id)).toBe(false);
    });

    test('closing a row with unsaved edits asks first, and a cancel keeps it', async () => {
        openBrowser(FILE.id);
        await settle();
        type('unsaved\n');
        confirmAnswer = false;
        await browserBridge.close(FILE.id);
        await settle();
        expect(confirms).toEqual(['discard unsaved changes?']);
        expect(server.deletes).toEqual([]);
        expect(q('.fscreen')).not.toBeNull();
        confirmAnswer = true;
        await browserBridge.close(FILE.id);
        await settle();
        expect(server.deletes).toEqual([FILE.id]);
        expect(q('.fscreen')).toBeNull();
        expect(document.getElementById('terminal-grid')!.hasAttribute('data-center-page')).toBe(false);
    });

    test('the title bar close button is the shared close: it asks first with unsaved edits, and closes a saved file', async () => {
        openBrowser(FILE.id);
        await settle();
        type('unsaved\n');
        confirmAnswer = false;
        q<HTMLButtonElement>('[data-file-close]')!.click();
        await settle();
        expect(confirms).toEqual(['discard unsaved changes?']);
        expect(server.deletes).toEqual([]);
        confirmAnswer = true;
        q<HTMLButtonElement>('[data-file-close]')!.click();
        await settle();
        expect(server.deletes).toEqual([FILE.id]);
        expect(q('.fscreen')).toBeNull();
    });

    test('a saved row closes with no question', async () => {
        await browserBridge.close(FILE.id);
        expect(confirms).toEqual([]);
        expect(server.deletes).toEqual([FILE.id]);
    });

    test('a binary file opens to the "can not show" view, with no editor and no save', async () => {
        openBrowser(BIN.id);
        await settle();
        expect(q('[data-file-cant="not_text"]')?.textContent).toContain('not text');
        expect(q('[data-file-editor]')).toBeNull();
        expect(q('[data-file-save]')).toBeNull();
    });

    test('a diff row shows the session diff read only: no editor, no save', async () => {
        openBrowser(DIFF.id);
        await settle();
        expect(q('[data-file-screen="diff"]')).not.toBeNull();
        expect(q('[data-file-diff] [data-git-diff-view]')).not.toBeNull();
        expect(q('[data-file-diff]')?.textContent).toContain('+added line');
        expect(q('[data-file-editor]')).toBeNull();
        expect(q('[data-file-save]')).toBeNull();
        expect(q('.fs-flag--quiet')?.textContent).toBe('read only');
        expect(server.reads).not.toContain(DIFF.id);
    });

    test('the files widget opens a file as a row of its session by the durable uuid, and shows it', async () => {
        const result = await openFromDrawer({ root: 'workdir', path: 'docs/notes.md', sessionId: 'ses_1', sessionRowId: 3, tmuxName: null });
        await settle();
        expect(result).toBe('opened');
        expect(server.posts).toEqual([{ root: 'workdir', path: 'docs/notes.md', session_uuid: 'u-1', kind: 'file' }]);
        expect(q('.fs-path')?.textContent).toBe('docs/notes.md');
        expect(location.hash).toBe('#browser/c1b2c3d4e5f60718');
    });

    test('with no session to name, the files widget keeps its own editor', async () => {
        expect(await openFromDrawer({ root: 'user', path: 'CLAUDE.md' })).toBe('unavailable');
        expect(server.posts).toEqual([]);
    });

    const tone = (): string | null => q('[data-file-save]')!.getAttribute('data-notes-light');

    test('the header is the notes control set in the notes order: toggle, disk, close (a markdown file shows the toggle)', async () => {
        server.files = [{ ...FILE, id: 'e1b2c3d4e5f60718', path: 'docs/a.md', title: 'a.md' }];
        server.contents['e1b2c3d4e5f60718'] = { id: 'e1b2c3d4e5f60718', viewable: true, content: '# hi\n', sha256: 's-m' };
        await openFiles.refresh(true);
        openBrowser('e1b2c3d4e5f60718');
        await settle();
        const kids = Array.from(q('.fs-actions [data-notes-controls]')!.querySelectorAll('[data-notes-mode], [data-file-save], [data-file-close]'));
        expect(kids.map((k) => k.getAttribute('data-notes-mode') ?? (k.hasAttribute('data-file-save') ? 'save' : 'close'))).toEqual(['edit', 'preview', 'save', 'close']);
        dropBuffer('e1b2c3d4e5f60718');
    });

    test('the toggle swaps the body and aria-checked follows, like the notepad; a non-markdown file has no toggle', async () => {
        openBrowser(FILE.id);
        await settle();
        expect(q('[data-notes-mode]')).toBeNull();
        dismissBrowserScreen();
        await settle();
        server.files = [{ ...FILE, id: 'e1b2c3d4e5f60718', path: 'docs/a.md', title: 'a.md' }];
        server.contents['e1b2c3d4e5f60718'] = { id: 'e1b2c3d4e5f60718', viewable: true, content: '# hi\n', sha256: 's-m' };
        await openFiles.refresh(true);
        openBrowser('e1b2c3d4e5f60718');
        await settle();
        expect(q('.fs-edit')!.hasAttribute('hidden')).toBe(true);
        expect(q('.fs-preview')).not.toBeNull();
        expect(q('.fs-edit')!.hasAttribute('hidden')).toBe(true);
        expect(q('[data-notes-mode="preview"]')!.getAttribute('aria-checked')).toBe('true');
        expect(q('[data-notes-mode="edit"]')!.getAttribute('aria-checked')).toBe('false');
        q<HTMLButtonElement>('[data-notes-mode="edit"]')!.click();
        flushSync();
        expect(q('.fs-preview')).toBeNull();
        expect(q('.fs-edit')!.hasAttribute('hidden')).toBe(false);
        dropBuffer('e1b2c3d4e5f60718');
    });

    test('the disk is disabled and green while clean, yellow and live once changed, green and disabled again after a save', async () => {
        openBrowser(FILE.id);
        await settle();
        expect(q<HTMLButtonElement>('[data-file-save]')!.disabled).toBe(true);
        expect(tone()).toBe('saved');
        type('print(2)\n');
        expect(q<HTMLButtonElement>('[data-file-save]')!.disabled).toBe(false);
        expect(tone()).toBe('pending');
        q<HTMLButtonElement>('[data-file-save]')!.click();
        await settle();
        expect(server.puts).toHaveLength(1);
        expect(tone()).toBe('saved');
        expect(q<HTMLButtonElement>('[data-file-save]')!.disabled).toBe(true);
    });

    test('a stale save turns the disk red with the conflict word, and a press points at the strip instead of writing', async () => {
        openBrowser(FILE.id);
        await settle();
        type('print(2)\n');
        server.disk[FILE.id] = 's-agent';
        q<HTMLButtonElement>('[data-file-save]')!.click();
        await settle();
        expect(tone()).toBe('error');
        expect(q('.oc-notes-save-word')?.textContent).toBe('save conflict');
        const puts = server.puts.length;
        q<HTMLButtonElement>('[data-file-save]')!.click();
        await settle();
        expect(server.puts).toHaveLength(puts);
        expect(document.activeElement?.closest('[data-file-stale]')).not.toBeNull();
    });

    test('Cmd+S still saves, and does nothing while clean', async () => {
        openBrowser(FILE.id);
        await settle();
        const press = (): void => { q('.fscreen')!.dispatchEvent(new KeyboardEvent('keydown', { key: 's', metaKey: true, bubbles: true, cancelable: true })); };
        press();
        await settle();
        expect(server.puts).toHaveLength(0);
        type('print(3)\n');
        press();
        await settle();
        expect(server.puts).toHaveLength(1);
    });

    test('the preview fills the pane inside the page gutter, with no document column cap, and code scrolls in its own box', () => {
        const css = readFileSync(resolve(__dirname, 'FileScreen.svelte'), 'utf8');
        const rule = (name: string): string => new RegExp(`${name.replace('.', '\\.')}\\s*\\{([^}]*)\\}`).exec(css)?.[1] ?? '';
        expect(rule('.fs-preview')).toContain('padding: var(--oc-gutter)');
        expect(rule('.fs-doc')).not.toMatch(/max-width|margin:\s*0 auto/);
        expect(rule('.fs-doc')).toMatch(/width:\s*100%/);
        expect(rule('.fs-doc')).toContain('overflow-wrap: anywhere');
        expect(/\.fs-doc :global\(pre\)\s*\{[^}]*overflow-x:\s*auto/.test(css)).toBe(true);
    });
});
