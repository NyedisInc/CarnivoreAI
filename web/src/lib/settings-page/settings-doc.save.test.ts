import { expect, test } from 'vitest';
import { SettingsDoc, type SettingsDocApi, type SettingsSummary } from './settings-doc.svelte';

function gate<T>(): { promise: Promise<T>; resolve: (v: T) => void } {
    let resolve!: (v: T) => void;
    const promise = new Promise<T>((r) => { resolve = r; });
    return { promise, resolve };
}

function api(over: Partial<SettingsDocApi> = {}): SettingsDocApi {
    return {
        get: () => Promise.resolve({} as SettingsSummary),
        patch: () => Promise.resolve({} as SettingsSummary),
        saveMinutes: () => Promise.resolve(true),
        minutes: () => ({ value: 30, min: 1, max: 999 }),
        ...over,
    };
}

test('a draft typed while the save is in flight is kept', async () => {
    const held = gate<SettingsSummary>();
    const doc = new SettingsDoc(api({ patch: () => held.promise }));
    doc.setDraft('development_root', '/tmp/first');
    const saving = doc.save();
    doc.setDraft('development_root', '/tmp/second');
    held.resolve({} as SettingsSummary);
    expect(await saving).toBe(true);
    expect(doc.drafts['development_root']).toBe('/tmp/second');
});

test('a minutes failure after a good patch marks only the minutes row', async () => {
    const doc = new SettingsDoc(api({ saveMinutes: () => Promise.resolve(false) }));
    doc.setDraft('development_root', '/tmp/x');
    doc.setDraft('auto_sleep_minutes', 45);
    expect(await doc.save()).toBe(false);
    expect(doc.status['auto_sleep_minutes']?.state).toBe('error');
    expect(doc.status['development_root']?.state).toBe('saved');
    expect('development_root' in doc.drafts).toBe(false);
    expect('auto_sleep_minutes' in doc.drafts).toBe(true);
});
