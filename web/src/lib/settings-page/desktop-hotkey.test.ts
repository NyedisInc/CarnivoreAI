import { describe, expect, it } from 'vitest';
import { acceleratorOf } from './desktop-hotkey';

const press = (code: string, mods: Partial<{ ctrlKey: boolean; altKey: boolean; shiftKey: boolean; metaKey: boolean }>) => ({
    code, ctrlKey: false, altKey: false, shiftKey: false, metaKey: false, ...mods,
});

describe('acceleratorOf (the hotkey row)', () => {
    it('spells a chord of two or more modifiers', () => {
        expect(acceleratorOf(press('KeyC', { ctrlKey: true, altKey: true, metaKey: true }))).toBe('Ctrl+Option+Cmd+C');
        expect(acceleratorOf(press('KeyK', { shiftKey: true, metaKey: true }))).toBe('Shift+Cmd+K');
    });
    it('refuses a single modifier on a letter, so Cmd+C is never offered (a global shortcut takes it from every app)', () => {
        expect(acceleratorOf(press('KeyC', { metaKey: true }))).toBeNull();
        expect(acceleratorOf(press('KeyV', { ctrlKey: true }))).toBeNull();
        expect(acceleratorOf(press('Space', { metaKey: true }))).toBeNull();
    });
    it('lets a function key carry one modifier', () => {
        expect(acceleratorOf(press('F5', { metaKey: true }))).toBe('Cmd+F5');
    });
});
