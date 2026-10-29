import { expect, test, vi } from 'vitest';
import { handleSettingsKey } from './settings-shortcut';

const ev = (over: Partial<KeyboardEvent>) =>
    ({ key: ',', metaKey: false, ctrlKey: false, altKey: false, shiftKey: false, preventDefault: vi.fn(), ...over }) as unknown as KeyboardEvent;

test('cmd+, opens settings and prevents the browser default', () => {
    const open = vi.fn();
    const e = ev({ metaKey: true });
    expect(handleSettingsKey(e, true, open)).toBe(true);
    expect(open).toHaveBeenCalledOnce();
    expect(e.preventDefault).toHaveBeenCalled();
});

test('ctrl+, is the chord off a mac', () => {
    const open = vi.fn();
    expect(handleSettingsKey(ev({ ctrlKey: true }), false, open)).toBe(true);
    expect(open).toHaveBeenCalledOnce();
});

test('plain comma and other chords do nothing', () => {
    const open = vi.fn();
    const plain = ev({});
    expect(handleSettingsKey(plain, true, open)).toBe(false);
    expect(handleSettingsKey(ev({ metaKey: true, shiftKey: true }), true, open)).toBe(false);
    expect(handleSettingsKey(ev({ ctrlKey: true }), true, open)).toBe(false);
    expect(open).not.toHaveBeenCalled();
    expect(plain.preventDefault).not.toHaveBeenCalled();
});
