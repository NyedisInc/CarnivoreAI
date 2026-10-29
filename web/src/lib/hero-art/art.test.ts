import { expect, test } from 'vitest';
import { ART_HEIGHT, ART_TOKENS, ART_WIDTH, heroShapes, prng } from './art';

test('the same seed gives the same art, ignoring case and surrounding space', () => {
    expect(heroShapes('Acme')).toEqual(heroShapes('Acme'));
    expect(heroShapes('  ACME ')).toEqual(heroShapes('acme'));
});

test('different seeds give different art', () => {
    const names = ['acme', 'zed co', 'alpha', 'beta', 'gamma', 'loose'];
    const drawn = new Set(names.map((n) => JSON.stringify(heroShapes(n))));
    expect(drawn.size).toBe(names.length);
});

test('every shape is inside the banner space and painted with a theme token only', () => {
    for (const name of ['acme', 'zed co', 'x']) {
        const shapes = heroShapes(name);
        expect(shapes.length).toBeGreaterThanOrEqual(7);
        for (const s of shapes) {
            expect(ART_TOKENS).toContain(s.token);
            expect(s.x).toBeGreaterThanOrEqual(0);
            expect(s.x).toBeLessThanOrEqual(ART_WIDTH);
            expect(s.y).toBeGreaterThanOrEqual(0);
            expect(s.y).toBeLessThanOrEqual(ART_HEIGHT);
            expect(s.opacity).toBeGreaterThan(0);
            expect(s.opacity).toBeLessThanOrEqual(1);
        }
    }
    expect(ART_TOKENS.every((t) => t.startsWith('--oc-'))).toBe(true);
});

test('the generator is seeded: same seed, same stream', () => {
    const a = prng(42);
    const b = prng(42);
    expect([a(), a(), a()]).toEqual([b(), b(), b()]);
});
