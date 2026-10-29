import { describe, expect, test } from 'vitest';

import { CATALOGS, registerFragment } from '../../../../client/js/i18n/catalogs.js';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { isPseudo } from '../../../../client/js/i18n/pseudo.js';
import { pluginSlices, registerPluginSlices, registerSlices } from './plugin-fragments';

function table(locale: string): Record<string, unknown> {
    return (CATALOGS as unknown as Record<string, { messages: Record<string, unknown> }>)[locale]!.messages;
}

describe('registerFragment', () => {
    test('adds the keys to en and a derived pseudo entry, once', () => {
        const slice = { 'cplug.zzprobe.hello': 'hello there', 'cplug.zzprobe.count': { one: '{count} thing', other: '{count} things' } };
        expect(registerFragment('zzprobe', slice)).toBe(2);
        expect(table('en')['cplug.zzprobe.hello']).toBe('hello there');
        expect(isPseudo(table('pseudo')['cplug.zzprobe.hello'])).toBe(true);
        expect(registerFragment('zzprobe', slice)).toBe(0);
        const i18n = createI18n({ locale: 'en' });
        expect(i18n.t('cplug.zzprobe.count', { count: 2 })).toBe('2 things');
    });

    test('refuses a key outside the plugin namespace, and a collision with a different value', () => {
        expect(() => registerFragment('zzprobe', { 'session.title': 'x' })).toThrow(/outside cplug\.zzprobe\./);
        expect(() => registerFragment('zzprobe', { 'cplug.zzprobe.hello': 'other words' })).toThrow(/redefines/);
        expect(() => registerFragment('zzother', { 'cplug.zzprobe.hello': 'hello there' })).toThrow(/outside/);
    });

    test('a runtime can extend its own catalog', () => {
        const i18n = createI18n({ locale: 'en' }) as { extendCatalog: (id: string, m: Record<string, string>) => number; t: (k: string) => string };
        expect(i18n.extendCatalog('zzprobe2', { 'cplug.zzprobe2.a': 'a b c' })).toBe(1);
        expect(i18n.t('cplug.zzprobe2.a')).toBe('a b c');
    });
});

describe('a bad slice (u140-06)', () => {
    test('is reported and skipped, the good ones still merge, nothing throws', () => {
        const seen: string[] = [];
        const failures = registerSlices(
            [
                ['zzbad', { 'session.title': 'outside my namespace' }],
                ['zzgood', { 'cplug.zzgood.a': 'fine' }],
            ],
            (id) => seen.push(id),
        );
        expect(failures.map((f) => f.pluginId)).toEqual(['zzbad']);
        expect(failures[0]!.reason).toMatch(/outside cplug\.zzbad\./);
        expect(table('en')['cplug.zzgood.a']).toBe('fine');
        expect(seen).toEqual(['zzgood']);
    });
});

describe('the shipped slices', () => {
    test('no shipped slice is refused (this is the build-time guard the load-time catch relies on)', () => {
        expect(registerPluginSlices()).toEqual([]);
    });

    test('there is one per migrated plugin and each sits in its own namespace', () => {
        const slices = pluginSlices();
        const ids = slices.map(([id]) => id);
        for (const id of ['flow', 'reviewboard', 'save', 'share', 'unread']) expect(ids).toContain(id);
        expect(ids).not.toContain('mcphealth');
        for (const [id, slice] of slices) {
            const keys = Object.keys(slice);
            expect(keys.length, id).toBeGreaterThan(0);
            expect(keys.every((k) => k.startsWith(`cplug.${id}.`)), id).toBe(true);
        }
    });

    test('registering them all (twice) makes every key resolvable', () => {
        registerPluginSlices();
        registerPluginSlices();
        for (const [, slice] of pluginSlices()) {
            for (const key of Object.keys(slice)) expect(Object.prototype.hasOwnProperty.call(table('en'), key), key).toBe(true);
        }
    });
});
