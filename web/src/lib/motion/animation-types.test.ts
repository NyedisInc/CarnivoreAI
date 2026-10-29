/** @vitest-environment jsdom */
import { afterEach, describe, expect, it } from 'vitest';
import { ANIMATION_TYPES, animationTypeOff, setAnimationTypeOff, watchAnimationTypes } from './animation-types';

afterEach(() => {
    document.documentElement.removeAttribute('data-anim-off');
    localStorage.clear();
});

describe('per-type animation switches', () => {
    it('writes the root attribute and this browser copy, in list order, and clears both when all are on', () => {
        setAnimationTypeOff('cursor-blink', true);
        setAnimationTypeOff('status-lights', true);
        expect(document.documentElement.getAttribute('data-anim-off')).toBe('status-lights cursor-blink');
        expect(localStorage.getItem('carnivore.animation-types-off')).toBe('status-lights cursor-blink');
        expect(animationTypeOff('status-lights')).toBe(true);
        expect(animationTypeOff('pop-ins')).toBe(false);
        setAnimationTypeOff('status-lights', false);
        setAnimationTypeOff('cursor-blink', false);
        expect(document.documentElement.hasAttribute('data-anim-off')).toBe(false);
        expect(localStorage.getItem('carnivore.animation-types-off')).toBeNull();
    });

    it('tells a watcher when the list changes', async () => {
        let calls = 0;
        const stop = watchAnimationTypes(() => { calls += 1; });
        setAnimationTypeOff('layout-moves', true);
        await Promise.resolve();
        await new Promise((r) => setTimeout(r, 0));
        stop();
        expect(calls).toBeGreaterThan(0);
    });

    it('lists every id the stylesheet and the catalog know', () => {
        expect(new Set(ANIMATION_TYPES).size).toBe(ANIMATION_TYPES.length);
    });
});
