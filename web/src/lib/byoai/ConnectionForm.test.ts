/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import ConnectionForm from './ConnectionForm.svelte';
import { setLocale } from '../i18n/index.svelte';
import type { Connection, Preset } from './api';
import { patchFor, type Draft } from './form-logic';

setLocale('en');

const preset = (over: Partial<Preset>): Preset => ({
    id: 'anthropic', label: 'anthropic', kind: 'cloud', capabilities: { chat: ['anthropic_messages'] }, base_url: 'https://api.anthropic.com',
    auth: 'x-api-key', key_required: true, auth_choices: [], fields: [], docs_url: '', default_models: [], model_source: 'discover', custom: false, ...over,
});
const PRESETS: Preset[] = [
    preset({ id: 'ollama', label: 'ollama', kind: 'local', base_url: 'http://127.0.0.1:11434/v1', auth: 'none', key_required: false }),
    preset({}),
];
const SAVED: Connection = {
    id: 'anthropic-1', preset: 'anthropic', label: 'work claude', base_url: 'https://api.anthropic.com', options: {}, enabled: true,
    key_host: 'https://api.anthropic.com', key_hint: 'wxyz', has_key: true, models: {},
};

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
    for (const m of mounted.splice(0)) await unmount(m);
    document.body.replaceChildren();
});

function render(connection: Connection | null = SAVED) {
    const saved: Draft[] = [];
    mounted.push(mount(ConnectionForm, {
        target: document.body,
        props: { presets: PRESETS, connection, onSave: (d: Draft) => saved.push(d), onCancel: () => {} },
    }));
    flushSync();
    const q = (name: string) => document.body.querySelector<HTMLInputElement>(`[data-ai="${name}"]`);
    const type = (el: HTMLInputElement, value: string) => {
        el.value = value;
        el.dispatchEvent(new Event('input', { bubbles: true }));
        flushSync();
    };
    return { saved, q, type };
}

function withMasking<T>(supported: boolean, fn: () => T): T {
    vi.stubGlobal('CSS', { supports: () => supported });
    try {
        return fn();
    } finally {
        vi.unstubAllGlobals();
    }
}

describe('the connection form', () => {
    test('the key field never renders a stored value', () => {
        const { q } = render();
        const key = q('key')!;
        expect(key.value).toBe('');
        expect(q('key-state')!.textContent).toContain('ends in wxyz');
        expect([...document.body.querySelectorAll('input')].every((i) => !i.value.includes('wxyz'))).toBe(true);
    });

    test('the key field is a never-password masked text input with every ignore attribute', () => {
        const key = withMasking(true, () => render(SAVED).q('key')!);
        expect(key.type).toBe('text');
        expect(key.classList.contains('oc-secret')).toBe(true);
        expect(key.getAttribute('autocomplete')).toBe('off');
        expect(key.getAttribute('autocapitalize')).toBe('off');
        expect(key.getAttribute('spellcheck')).toBe('false');
        for (const name of ['data-1p-ignore', 'data-lpignore', 'data-bwignore']) expect(key.getAttribute(name)).toBe('true');
        expect(key.getAttribute('data-form-type')).toBe('other');
    });

    test('a browser that cannot mask falls back to a password input', () => {
        expect(withMasking(false, () => render(SAVED).q('key')!).type).toBe('password');
    });

    test('a blank key field leaves the stored key untouched', () => {
        const { q, saved } = render();
        q('save')!.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
        flushSync();
        expect(saved).toHaveLength(1);
        expect(saved[0]!.key).toBe('');
        expect(saved[0]!.clearKey).toBe(false);
        const body = patchFor(PRESETS[1]!, SAVED, saved[0]!, 7);
        expect(body).toEqual({ expected_revision: 7 });
        expect('key' in body).toBe(false);
    });

    test('a typed key is sent, trimmed', () => {
        const { q, type, saved } = render();
        type(q('key')!, '  sk-new-secret-value  ');
        document.body.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
        flushSync();
        expect(patchFor(PRESETS[1]!, SAVED, saved[0]!, 7).key).toBe('sk-new-secret-value');
    });

    test('a host change on a connection with a key warns, unless a new key is typed', () => {
        const { q, type } = render();
        expect(q('host-warning')).toBeNull();
        type(q('base-url')!, 'https://api.anthropic.com/v1');
        expect(q('host-warning')).toBeNull();
        type(q('base-url')!, 'HTTPS://API.anthropic.com.:443/v1');
        expect(q('host-warning')).toBeNull();
        type(q('base-url')!, 'http://api.anthropic.com');
        expect(q('host-warning')).not.toBeNull();
        type(q('base-url')!, 'https://api.anthropic.com:8443');
        expect(q('host-warning')).not.toBeNull();
        type(q('base-url')!, 'https://other.example.com');
        expect(q('host-warning')!.textContent).toContain('clears the stored key');
        expect(q('host-warning')!.textContent).toContain('api.anthropic.com');
        type(q('key')!, 'a-replacement-value');
        expect(q('host-warning')).toBeNull();
    });

    test('an edit that leaves the base url alone never warns', () => {
        const { q, type } = render();
        type(q('label')!, 'renamed');
        expect(q('host-warning')).toBeNull();
    });

    test('a connection with no key never warns about a host change', () => {
        const { q, type } = render({ ...SAVED, has_key: false, key_host: null, key_hint: '' });
        type(q('base-url')!, 'https://other.example.com');
        expect(q('host-warning')).toBeNull();
    });
});
