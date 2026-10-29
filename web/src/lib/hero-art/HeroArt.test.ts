/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import HeroArt from './HeroArt.svelte';

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
    for (const c of mounted.splice(0)) await unmount(c);
    document.body.replaceChildren();
});

function render(props: Record<string, unknown>): HTMLElement {
    const target = document.createElement('div');
    document.body.append(target);
    mounted.push(mount(HeroArt, { target, props: props as { seed: string } }));
    flushSync();
    return target.querySelector<HTMLElement>('[data-hero-art]')!;
}

test('a banner with no image is the generated art for its seed, deterministic across renders', () => {
    const a = render({ seed: 'Acme' });
    const b = render({ seed: 'acme' });
    expect(a.classList.contains('hero-art--banner')).toBe(true);
    expect(a.dataset.heroSource).toBe('generated');
    expect(a.querySelector('svg')!.innerHTML).toBe(b.querySelector('svg')!.innerHTML);
    expect(render({ seed: 'zed' }).querySelector('svg')!.innerHTML).not.toBe(a.querySelector('svg')!.innerHTML);
});

test('the art is cropped from the centre and coloured by theme variables only', () => {
    const el = render({ seed: 'acme', shape: 'square', size: '24px' });
    expect(el.classList.contains('hero-art--square')).toBe(true);
    expect(el.getAttribute('style')).toContain('--hero-art-size: 24px');
    expect(el.querySelector('svg')!.getAttribute('preserveAspectRatio')).toBe('xMidYMid slice');
    const fills = [...el.querySelectorAll<SVGElement>('svg [style]')].map((n) => n.getAttribute('style')!);
    expect(fills.length).toBeGreaterThan(0);
    for (const f of fills) expect(f).toMatch(/fill:\s*var\(--oc-[a-z0-9-]+\)/);
    expect(el.querySelector('[data-hero-img]')).toBeNull();
});
