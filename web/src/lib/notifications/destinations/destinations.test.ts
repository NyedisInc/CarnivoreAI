/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import DestinationsPanel from './DestinationsPanel.svelte';
import { ApiError } from '../../../opscenter/api/auth.svelte';
import { setLocale } from '../../i18n/index.svelte';
import { notify } from './store.svelte';
import type { Destination, Kind, KindField } from './api';
import { complete, createBody, initialDraft, patchBody, saveProblem } from './form-logic';

setLocale('en');

const f = (name: string, type: string, required: boolean, choices: string[] = []): KindField => ({ name, type, required, choices });
const KINDS: Kind[] = [
    { id: 'slack', label_key: 'notify.kind.slack', sms_like: false, details_allowed: true, virtual: false, public_fields: [], secret_fields: [f('url', 'url', true)] },
    { id: 'webhook', label_key: 'notify.kind.webhook', sms_like: false, details_allowed: true, virtual: false, allow_private: true, public_fields: [f('header_name', 'text', false)],
        secret_fields: [f('url', 'url', true), f('signing_secret', 'secret', false), f('header_value', 'secret', false)] },
    { id: 'email', label_key: 'notify.kind.email', sms_like: false, details_allowed: true, virtual: false,
        public_fields: [f('smtp_host', 'text', true), f('smtp_port', 'int', true), f('security', 'enum', true, ['starttls', 'tls', 'plain'])],
        secret_fields: [f('user', 'secret', false), f('password', 'secret', false), f('from_address', 'secret', true), f('recipients', 'list', true)] },
    { id: 'twilio', label_key: 'notify.kind.twilio', sms_like: true, details_allowed: false, virtual: false, public_fields: [],
        secret_fields: [f('sid', 'secret', true), f('token', 'secret', true), f('from_number', 'secret', true), f('numbers', 'list', true)] },
    { id: 'ntfy', label_key: 'notify.kind.ntfy', sms_like: false, details_allowed: true, virtual: false, allow_private: true,
        public_fields: [f('base_url', 'url', false)], secret_fields: [f('topic', 'secret', true), f('token', 'secret', false)] },
    { id: 'webpush', label_key: 'notify.kind.webpush', sms_like: false, details_allowed: false, virtual: true, public_fields: [], secret_fields: [] },
];
const EXTRAS = { away: false, quiet: null, reminder_minutes: null, projects: [], details: false };
const dest = (over: Partial<Destination>): Destination => ({
    id: 'd_aaaaaaaaaaaa', kind: 'slack', name: 'ops channel', enabled: true, scope: 'global', pinned: false, config: {}, secrets: { url: { set: true } },
    extras: EXTRAS, status: null, ...over,
});

interface Call { method: string; path: string; body: Record<string, unknown> | null }

function fake(destinations: Destination[], answers: Record<string, () => unknown> = {}) {
    const calls: Call[] = [];
    const fetcher = (async (path: string, init: RequestInit = {}) => {
        const method = init.method ?? 'GET';
        calls.push({ method, path, body: typeof init.body === 'string' ? JSON.parse(init.body) : null });
        const key = `${method} ${path}`;
        if (answers[key]) return answers[key]!();
        if (path === '/notifications/types') return { families: [], types: [], kinds: KINDS };
        if (path === '/notifications/settings') return { revision: 1, paused: false, destinations };
        throw new Error(`unexpected ${key}`);
    }) as never;
    return { fetcher, calls };
}

const mounted: ReturnType<typeof mount>[] = [];
beforeEach(() => { notify.kinds = []; notify.destinations = []; notify.loaded = false; notify.problem = ''; });
afterEach(async () => {
    for (const m of mounted.splice(0)) await unmount(m);
    document.body.replaceChildren();
});

async function render(destinations: Destination[], answers: Record<string, () => unknown> = {}) {
    const rig = fake(destinations, answers);
    mounted.push(mount(DestinationsPanel, { target: document.body, props: { fetcher: rig.fetcher } }));
    await vi.waitFor(() => expect(notify.loaded).toBe(true));
    flushSync();
    return rig;
}
const q = (sel: string) => document.body.querySelector<HTMLElement>(sel);
const click = async (sel: string) => { q(sel)!.click(); flushSync(); await Promise.resolve(); };
const type = (el: HTMLElement, value: string) => { (el as HTMLInputElement).value = value; el.dispatchEvent(new Event('input', { bubbles: true })); flushSync(); };

const pickKind = async (id: string) => {
    q('[data-ai="kind-input"]')!.click();
    flushSync();
    q(`[data-ai="kind-option"][data-id="${id}"]`)!.click();
    flushSync();
    await Promise.resolve();
};

describe('the kind picker', () => {
    test('is the custom listbox, not a native select: grouped, one mark per row, and a pick sets the kind and its fields', async () => {
        await render([]);
        await click('[data-notify="add"]');
        expect(q('select[data-notify="kind"]')).toBeNull();
        q('[data-ai="kind-input"]')!.click();
        flushSync();
        const options = [...document.body.querySelectorAll('[data-ai="kind-option"]')];
        expect(options.length).toBe(5);
        for (const o of options) expect(o.querySelector('svg')).not.toBeNull();
        expect([...document.body.querySelectorAll('.ai-pick__head')].map((h) => h.textContent)).toEqual(['chat', 'push', 'sms', 'other']);
        await pickKind('email');
        expect(q('[data-notify="field-smtp_host"]')).not.toBeNull();
        expect(q('[data-notify="secret-url"]')).toBeNull();
    });
});

describe('secrets never render', () => {
    test('a response that wrongly carried a secret value never reaches the screen', async () => {
        const leaky = dest({ config: { url: 'https://hooks.example/LEAKED-CONFIG' }, secrets: { url: { set: true, value: 'LEAKED-VALUE' } as never } });
        const asString = dest({ id: 'd_bbbbbbbbbbbb', name: 'second', secrets: { url: 'LEAKED-STRING' as never } });
        await render([leaky, asString]);
        await click('[data-notify="edit"]');
        expect(document.body.innerHTML).not.toContain('LEAKED');
        for (const input of document.body.querySelectorAll('input')) expect(input.value).not.toContain('LEAKED');
        expect(q('[data-notify-dest="d_bbbbbbbbbbbb"] [data-notify="secrets-state"]')!.textContent).toContain('not set');
    });

    test('the edit form shows set or not set as text, with an empty masked input', async () => {
        await render([dest({})]);
        await click('[data-notify="edit"]');
        const input = q('[data-notify="secret-url"]') as HTMLInputElement;
        expect(input.value).toBe('');
        expect(input.classList.contains('oc-secret')).toBe(true);
        expect(q('[data-notify="secret-state-url"]')!.textContent).toBe('set');
    });
});

describe('blank secret means untouched', () => {
    test('the PATCH body omits a blank secret and carries only the typed one', async () => {
        const rig = await render([dest({ kind: 'webhook', secrets: { url: { set: true }, signing_secret: { set: true }, header_value: { set: false } } })], {
            'PATCH /notifications/destinations/d_aaaaaaaaaaaa': () => ({ destination: dest({ kind: 'webhook', name: 'renamed' }) }),
        });
        await click('[data-notify="edit"]');
        type(q('[data-notify="name"]')!, 'renamed');
        type(q('[data-notify="secret-header_value"]')!, 'tok');
        await click('[data-notify="save"]');
        await vi.waitFor(() => expect(rig.calls.some((c) => c.method === 'PATCH')).toBe(true));
        const body = rig.calls.find((c) => c.method === 'PATCH')!.body!;
        expect(body.secrets).toEqual({ header_value: 'tok' });
        expect(body.name).toBe('renamed');
    });

    test('no typed secret means no secrets key at all', () => {
        const kind = KINDS[0]!;
        const body = patchBody(kind, initialDraft(kind, dest({})), dest({}));
        expect('secrets' in body).toBe(false);
    });

    test('a list secret is sent as an array and a pinned destination keeps writing locally', () => {
        const kind = KINDS[2]!;
        const draft = { ...initialDraft(kind, null), name: 'mail', config: { smtp_host: 'smtp.x', smtp_port: '587', security: 'starttls' },
            secrets: { from_address: 'a@x', recipients: 'b@x, c@x\nd@x' } };
        const body = createBody(kind, draft, 'global');
        expect(body.secrets).toEqual({ from_address: 'a@x', recipients: ['b@x', 'c@x', 'd@x'] });
        expect(body.config).toEqual({ smtp_host: 'smtp.x', smtp_port: 587, security: 'starttls' });
        expect(patchBody(kind, draft, dest({ pinned: true })).scope).toBe('local');
    });
});

describe('the test button', () => {
    const route = 'POST /notifications/destinations/d_aaaaaaaaaaaa/test';

    test('idle, then sending, then ok', async () => {
        let release: (v: unknown) => void = () => {};
        await render([dest({})], { [route]: () => new Promise((r) => { release = r; }) });
        expect(q('[data-notify="test"]')!.textContent).toBe('test');
        await click('[data-notify="test"]');
        expect(q('[data-notify="test"]')!.textContent).toContain('sending');
        expect((q('[data-notify="test"]') as HTMLButtonElement).disabled).toBe(true);
        release({ ok: true, failure: null, status_code: 200 });
        await vi.waitFor(() => expect(q('[data-notify="test-result"]')?.dataset['state']).toBe('ok'));
    });

    test('failed says the failure class in plain words', async () => {
        await render([dest({})], { [route]: () => ({ ok: false, failure: 'auth', status_code: 401 }) });
        await click('[data-notify="test"]');
        await vi.waitFor(() => expect(q('[data-notify="test-result"]')?.dataset['state']).toBe('failed'));
        expect(q('[data-notify="test-result"]')!.textContent).toContain('refused the credentials');
    });

    test('a 429 says wait', async () => {
        await render([dest({})], { [route]: () => { throw new ApiError('slow', 429); } });
        await click('[data-notify="test"]');
        await vi.waitFor(() => expect(q('[data-notify="test-result"]')?.dataset['state']).toBe('failed'));
        expect(q('[data-notify="test-result"]')!.textContent).toContain('wait');
    });
});

describe('the webhook signing secret', () => {
    test('shows once after create with a copy button, and is gone after a reload', async () => {
        const made = dest({ id: 'd_cccccccccccc', kind: 'webhook', name: 'hook', secrets: { url: { set: true }, signing_secret: { set: true }, header_value: { set: false } } });
        const rig = await render([], { 'POST /notifications/destinations': () => ({ destination: made, signing_secret: 'SIGN-ONCE-123' }) });
        await click('[data-notify="add"]');
        await pickKind('webhook');
        type(q('[data-notify="name"]')!, 'hook');
        type(q('[data-notify="secret-url"]')!, 'https://example.test/h');
        await click('[data-notify="save"]');
        await vi.waitFor(() => expect(q('[data-notify="signing-value"]')?.textContent).toBe('SIGN-ONCE-123'));
        expect(q('[data-notify="signing-copy"]')).not.toBeNull();
        expect(q('[data-notify="signing"]')!.textContent).toContain('shown once');
        expect(rig.calls.find((c) => c.method === 'POST')!.body).toMatchObject({ kind: 'webhook', scope: 'global', secrets: { url: 'https://example.test/h' } });
        for (const m of mounted.splice(0)) await unmount(m);
        document.body.replaceChildren();
        notify.loaded = false;
        await render([made]);
        expect(document.body.innerHTML).not.toContain('SIGN-ONCE-123');
        expect(q('[data-notify="signing"]')).toBeNull();
    });
});

describe('local scope', () => {
    test('a pinned destination shows the local badge and reset to global calls DELETE /overrides for it', async () => {
        const rig = await render([dest({ pinned: true })], { 'DELETE /notifications/overrides?path=dest%2Fd_aaaaaaaaaaaa': () => ({ revision: 2, reset: true }) });
        expect(q('[data-notify="local-badge"]')).not.toBeNull();
        await click('[data-notify="reset"]');
        await vi.waitFor(() => expect(rig.calls.some((c) => c.method === 'DELETE')).toBe(true));
        expect(rig.calls.find((c) => c.method === 'DELETE')!.path).toBe('/notifications/overrides?path=dest%2Fd_aaaaaaaaaaaa');
    });

    test('a global destination offers pin, which PATCHes scope local; a local-scope one has a badge and no reset', async () => {
        const rig = await render([dest({}), dest({ id: 'd_dddddddddddd', name: 'mine', scope: 'local' })], {
            'PATCH /notifications/destinations/d_aaaaaaaaaaaa': () => ({ destination: dest({ pinned: true }) }),
        });
        expect(q('[data-notify-dest="d_dddddddddddd"] [data-notify="local-badge"]')).not.toBeNull();
        expect(q('[data-notify-dest="d_dddddddddddd"] [data-notify="reset"]')).toBeNull();
        expect(q('[data-notify-dest="d_aaaaaaaaaaaa"] [data-notify="local-badge"]')).toBeNull();
        await click('[data-notify-dest="d_aaaaaaaaaaaa"] [data-notify="pin"]');
        await vi.waitFor(() => expect(rig.calls.some((c) => c.method === 'PATCH')).toBe(true));
        expect(rig.calls.find((c) => c.method === 'PATCH')!.body).toEqual({ enabled: true, scope: 'local' });
    });
});

describe('extras and details', () => {
    test('an sms-like kind hides details; a chat kind shows it', async () => {
        await render([dest({ id: 'd_eeeeeeeeeeee', kind: 'twilio', secrets: {} }), dest({})]);
        await click('[data-notify-dest="d_eeeeeeeeeeee"] [data-notify="extras-toggle"]');
        expect(q('[data-notify-dest="d_eeeeeeeeeeee"] [data-notify="extra-details"]')).toBeNull();
        await click('[data-notify-dest="d_aaaaaaaaaaaa"] [data-notify="extras-toggle"]');
        expect(q('[data-notify-dest="d_aaaaaaaaaaaa"] [data-notify="extra-details"]')).not.toBeNull();
    });

    test('saving extras PUTs them with the local scope choice', async () => {
        const rig = await render([dest({})], { 'PUT /notifications/destinations/d_aaaaaaaaaaaa/extras': () => ({ destination: dest({}) }) });
        await click('[data-notify="extras-toggle"]');
        await click('[data-notify="extra-away"]');
        await click('[data-notify="extra-local"]');
        type(q('[data-notify="extra-projects"]')!, 'alpha, beta');
        await click('[data-notify="extras-save"]');
        await vi.waitFor(() => expect(rig.calls.some((c) => c.method === 'PUT')).toBe(true));
        expect(rig.calls.find((c) => c.method === 'PUT')!.body).toEqual({ away: true, quiet: null, reminder_minutes: null, projects: ['alpha', 'beta'], details: false, scope: 'local' });
    });
});

describe('the form for each kind', () => {
    test.each([
        ['slack', ['secret-url']],
        ['webhook', ['secret-url', 'field-header_name']],
        ['email', ['field-smtp_host', 'field-smtp_port', 'field-security', 'secret-from_address', 'secret-recipients']],
        ['twilio', ['secret-sid', 'secret-token', 'secret-from_number', 'secret-numbers']],
    ])('%s renders its fields', async (id, fields) => {
        await render([]);
        await click('[data-notify="add"]');
        await pickKind(id);
        for (const name of fields) expect(q(`[data-notify="${name}"]`), `${id} ${name}`).not.toBeNull();
        expect((q('[data-notify="save"]') as HTMLButtonElement).disabled).toBe(true);
    });

    test('web push is not offered in the add form', async () => {
        await render([]);
        await click('[data-notify="add"]');
        q('[data-ai="kind-input"]')!.click();
        flushSync();
        expect([...document.body.querySelectorAll('[data-ai="kind-option"]')].map((o) => o.getAttribute('data-id'))).not.toContain('webpush');
    });

    test('a number input binds a JS number or null: complete and the bodies still work, and the port goes out as an int', () => {
        const kind = KINDS.find((k) => k.id === 'email')!;
        const base = { ...initialDraft(kind, null), name: 'mail', secrets: { from_address: 'a@b.c', recipients: 'x@y.z' } };
        const typed = { ...base, config: { smtp_host: 'smtp.x', smtp_port: 2525 as unknown as string, security: 'plain' } };
        expect(complete(kind, typed, null)).toBe(true);
        expect(createBody(kind, typed, 'global').config).toEqual({ smtp_host: 'smtp.x', smtp_port: 2525, security: 'plain' });
        const emptied = { ...typed, config: { ...typed.config, smtp_port: null as unknown as string } };
        expect(complete(kind, emptied, null)).toBe(false);
        expect(createBody(kind, emptied, 'global').config).not.toHaveProperty('smtp_port');
    });
});

describe('the private-address switch (this computer only)', () => {
    const openAdd = async (id: string) => {
        await render([]);
        await click('[data-notify="add"]');
        await pickKind(id);
    };

    test.each([['webhook', true], ['ntfy', true], ['slack', false], ['email', false], ['twilio', false]])('%s shows the toggle: %s', async (id, shown) => {
        await openAdd(id as string);
        expect(q('[data-notify="allow-private"]') !== null).toBe(shown);
        if (shown) {
            expect(q('[data-notify="allow-private"]')!.textContent).toContain('this computer only');
            expect(q('[data-notify="allow-private"]')!.textContent).toContain('never synced');
        }
    });

    test('create sends it, edit starts from the saved value and patch sends the change', async () => {
        const rig = await render([dest({ kind: 'webhook', allow_private: true, secrets: { url: { set: true } } })], {
            'PATCH /notifications/destinations/d_aaaaaaaaaaaa': () => ({ destination: dest({ kind: 'webhook', allow_private: false }) }),
        });
        await click('[data-notify="edit"]');
        expect(q('[data-notify="allow-private"]')!.getAttribute('aria-checked')).toBe('true');
        await click('[data-notify="allow-private"]');
        expect(q('[data-notify="allow-private"]')!.getAttribute('aria-checked')).toBe('false');
        await click('[data-notify="save"]');
        await vi.waitFor(() => expect(rig.calls.some((c) => c.method === 'PATCH')).toBe(true));
        expect(rig.calls.find((c) => c.method === 'PATCH')!.body!.allow_private).toBe(false);
        const kind = KINDS.find((k) => k.id === 'ntfy')!;
        const draft = { ...initialDraft(kind, null), name: 'n', allowPrivate: true, secrets: { topic: 't' } };
        expect(createBody(kind, draft, 'global').allow_private).toBe(true);
        const slack = KINDS.find((k) => k.id === 'slack')!;
        expect(createBody(slack, { ...initialDraft(slack, null), name: 's' }, 'global')).not.toHaveProperty('allow_private');
    });

    test('a refused save shows the plain sentence for https and for a private address', () => {
        const refusal = (code: string) => new ApiError('invalid', 422, null, { detail: { error: 'invalid', fields: { url: code } } });
        expect(saveProblem(refusal('https_required'), (k) => k)).toBe('settings.notify.dest.problem.https_required');
        expect(saveProblem(refusal('private_address'), (k) => k)).toBe('settings.notify.dest.problem.private_address');
        expect(saveProblem(refusal('required'), (k) => k)).toBeNull();
        expect(saveProblem(new Error('x'), (k) => k)).toBeNull();
    });
});

describe('the plain-http switch (this computer only, needs the private switch)', () => {
    const openAdd = async (id: string) => {
        await render([]);
        await click('[data-notify="add"]');
        await pickKind(id);
    };

    test.each([['webhook', true], ['ntfy', true], ['slack', false], ['email', false], ['twilio', false]])('%s shows the toggle: %s', async (id, shown) => {
        await openAdd(id as string);
        expect(q('[data-notify="allow-plain-http"]') !== null).toBe(shown);
        if (shown) {
            const text = q('[data-notify="allow-plain-http"]')!.textContent!;
            expect(text).toContain('allow plain http on this network');
            expect(text).toContain('this computer only');
            expect(text).toContain('unencrypted');
        }
    });

    test('it is disabled until the private switch is on, and turning private off clears it', async () => {
        await openAdd('webhook');
        const plain = () => q('[data-notify="allow-plain-http"]') as HTMLButtonElement;
        expect(plain().disabled).toBe(true);
        await click('[data-notify="allow-private"]');
        expect(plain().disabled).toBe(false);
        await click('[data-notify="allow-plain-http"]');
        expect(plain().getAttribute('aria-checked')).toBe('true');
        await click('[data-notify="allow-private"]');
        expect(plain().disabled).toBe(true);
        expect(plain().getAttribute('aria-checked')).toBe('false');
    });

    test('the payload carries it, edit starts from the saved value, other kinds never send it', async () => {
        const kind = KINDS.find((k) => k.id === 'ntfy')!;
        const draft = { ...initialDraft(kind, null), name: 'n', allowPrivate: true, allowPlainHttp: true, secrets: { topic: 't' } };
        expect(createBody(kind, draft, 'global')).toMatchObject({ allow_private: true, allow_plain_http: true });
        expect(createBody(kind, { ...draft, allowPrivate: false }, 'global').allow_plain_http).toBe(false);
        const saved = dest({ kind: 'webhook', allow_private: true, allow_plain_http: true, secrets: { url: { set: true } } });
        expect(initialDraft(KINDS.find((k) => k.id === 'webhook')!, saved).allowPlainHttp).toBe(true);
        const slack = KINDS.find((k) => k.id === 'slack')!;
        expect(createBody(slack, { ...initialDraft(slack, null), name: 's' }, 'global')).not.toHaveProperty('allow_plain_http');
    });
});
