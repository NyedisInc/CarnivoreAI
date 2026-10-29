/** @vitest-environment jsdom */
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

vi.mock('../help/feature-media', () => ({ fetchFeatureMediaBlob: vi.fn() }));

import { fetchFeatureMediaBlob } from '../help/feature-media';
import GuideShot from './GuideShot.svelte';
import { GUIDE_SECTIONS } from './guide-content';
import { followGuideTarget } from './guide-nav';
import { isFragmentTarget, type GuideBlock, type Hotspot } from './guide-parse';
import { settingsSectionOf } from '../settings-page/settings-hash';

const ROOT = resolve(process.cwd(), '..');
const LIB = resolve(process.cwd(), 'src/lib');

function routeBases(): Set<string> {
    const found = new Set<string>();
    const walk = (dir: string): void => {
        for (const name of readdirSync(dir)) {
            const path = join(dir, name);
            if (statSync(path).isDirectory()) walk(path);
            else if (name === 'screen-host.ts') {
                for (const m of readFileSync(path, 'utf8').matchAll(/_HASH = '(#[a-z-]+)'/g)) found.add(m[1] as string);
            }
        }
    };
    walk(LIB);
    const registry = readFileSync(join(LIB, 'menu-page', 'menu-pages.ts'), 'utf8');
    for (const list of registry.matchAll(/hashes: \[([^\]]*)\]/g)) {
        for (const m of (list[1] as string).matchAll(/'(#[a-z-]+)'/g)) found.add(m[1] as string);
    }
    return found;
}

function resolves(target: string, bases: Set<string>): boolean {
    if (!isFragmentTarget(target)) return false;
    const [base, rest] = [target.split('/')[0] as string, target.split('/')[1]];
    if (!bases.has(base)) return false;
    if (!rest) return true;
    if (base === '#docs') return GUIDE_SECTIONS.some((s) => s.id === rest) && target.split('/').length === 2;
    if (base === '#settings') return settingsSectionOf(target) !== null;
    return false;
}

const shots = GUIDE_SECTIONS.flatMap((s) => s.doc.blocks.filter((b): b is Extract<GuideBlock, { kind: 'shot' }> => b.kind === 'shot').map((b) => ({ section: s.id, shot: b })));

describe('the pictures the guide names', () => {
    test('there are at least two, each with marks, and every one is a captured feature image', () => {
        expect(shots.length).toBeGreaterThanOrEqual(2);
        for (const { section, shot } of shots) {
            const where = `${section}: ${shot.feature}/${shot.file}`;
            expect(shot.hotspots.length, where).toBeGreaterThan(0);
            expect(existsSync(join(ROOT, 'features/media', shot.feature, shot.file)), `${where} exists`).toBe(true);
            const catalog = JSON.parse(readFileSync(join(ROOT, 'features/catalog', `${shot.feature}.json`), 'utf8')) as { media: { file: string }[] };
            expect(catalog.media.map((m) => m.file), `${where} is listed`).toContain(shot.file);
            const spec = JSON.parse(readFileSync(join(ROOT, 'features/capture', `${shot.feature}.json`), 'utf8')) as { shots: { name: string; kind: string }[] };
            const stem = shot.file.replace(/\.[^.]+$/, '');
            expect(spec.shots.map((s) => s.name), `${where} has a capture shot`).toContain(stem);
        }
    });

    test('every mark target and every guide link resolves to a real page', () => {
        const bases = routeBases();
        expect([...bases]).toEqual(expect.arrayContaining(['#docs', '#settings', '#projects', '#sessions', '#ledger', '#themes', '#changelog', '#shortcuts']));
        const links: string[] = [];
        for (const { shot } of shots) for (const h of shot.hotspots) links.push(h.target);
        for (const s of GUIDE_SECTIONS) {
            for (const b of s.doc.blocks) {
                if (b.kind !== 'md') continue;
                const walk = (runs: unknown): void => {
                    for (const run of runs as { kind: string; href?: string; children?: unknown[] }[]) {
                        if (run.kind === 'link' && run.href?.startsWith('#')) links.push(run.href);
                        if (run.children) walk(run.children);
                    }
                };
                for (const block of b.blocks) {
                    if (block.kind === 'list') block.items.forEach(walk);
                    else if ('children' in block) walk(block.children);
                }
            }
        }
        expect(links.length).toBeGreaterThan(8);
        for (const link of links) expect(resolves(link, bases), link).toBe(true);
    });
});

describe('an annotated picture', () => {
    const marks: Hotspot[] = [
        { x: 10, y: 20, target: '#projects', title: 'projects', text: 'every project.' },
        { x: 80, y: 70, target: '#settings/appearance', title: 'look', text: 'colors and rows.' },
    ];
    let mounted: Record<string, unknown> | null = null;

    beforeEach(() => {
        vi.mocked(fetchFeatureMediaBlob).mockResolvedValue(new Blob(['x'], { type: 'image/png' }));
        URL.createObjectURL = vi.fn(() => 'blob:test');
        URL.revokeObjectURL = vi.fn();
    });
    afterEach(() => {
        if (mounted) unmount(mounted);
        mounted = null;
        document.body.innerHTML = '';
        window.location.hash = '';
        vi.restoreAllMocks();
    });

    async function render(): Promise<HTMLElement> {
        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(GuideShot, { target, props: { feature: 'user-guide', file: 'home.png', alt: 'the home screen', hotspots: marks } });
        for (let i = 0; i < 5; i += 1) await Promise.resolve();
        flushSync();
        return target;
    }

    test('draws the picture with its marks at the given percentages', async () => {
        const target = await render();
        expect(fetchFeatureMediaBlob).toHaveBeenCalledWith('user-guide', 'home.png');
        expect(target.querySelector('img')?.getAttribute('alt')).toBe('the home screen');
        const buttons = [...target.querySelectorAll<HTMLButtonElement>('[data-guide-mark]')];
        expect(buttons.map((b) => b.textContent)).toEqual(['1', '2']);
        expect(buttons[0]?.style.left).toBe('10%');
        expect(buttons[0]?.style.top).toBe('20%');
        expect(buttons[1]?.getAttribute('aria-label')).toBe('2. look. colors and rows.');
    });

    test('hover and focus show the words; leaving hides them', async () => {
        const target = await render();
        const first = target.querySelector<HTMLButtonElement>('[data-guide-mark="1"]')!;
        expect(target.querySelector('[data-guide-tip]')).toBeNull();
        first.dispatchEvent(new MouseEvent('mouseenter'));
        flushSync();
        expect(target.querySelector('[data-guide-tip]')?.textContent).toContain('1. projects');
        first.dispatchEvent(new MouseEvent('mouseleave'));
        flushSync();
        expect(target.querySelector('[data-guide-tip]')).toBeNull();
        const second = target.querySelector<HTMLButtonElement>('[data-guide-mark="2"]')!;
        second.dispatchEvent(new FocusEvent('focus'));
        flushSync();
        const tip = target.querySelector('[data-guide-tip]') as HTMLElement;
        expect(tip.textContent).toContain('2. look');
        expect(tip.className).toContain('shot__tip--left');
        expect(tip.className).toContain('shot__tip--up');
    });

    test('clicking a mark, or its entry in the list, opens the page it points at', async () => {
        const target = await render();
        target.querySelector<HTMLButtonElement>('[data-guide-mark="2"]')!.click();
        expect(window.location.hash).toBe('#settings/appearance');
        target.querySelector<HTMLButtonElement>('[data-guide-item="1"]')!.click();
        expect(window.location.hash).toBe('#projects');
    });

    test('the marks are real buttons in tab order, so enter and space work', async () => {
        const target = await render();
        for (const b of target.querySelectorAll<HTMLElement>('[data-guide-mark], [data-guide-item]')) {
            expect(b.tagName).toBe('BUTTON');
            expect(b.getAttribute('type')).toBe('button');
            expect(b.tabIndex).toBe(0);
        }
    });

    test('a picture that fails to load says so and keeps the list of marks', async () => {
        vi.mocked(fetchFeatureMediaBlob).mockRejectedValue(new Error('404'));
        const target = await render();
        expect(target.querySelector('[data-guide-shot-failed]')).not.toBeNull();
        expect(target.querySelector('[data-guide-mark]')).toBeNull();
        expect(target.querySelectorAll('[data-guide-item]').length).toBe(2);
    });
});

describe('followGuideTarget', () => {
    afterEach(() => {
        window.location.hash = '';
    });

    test('sets the hash, re-fires hashchange for the hash it already has, and refuses a non-fragment', () => {
        const heard = vi.fn();
        window.addEventListener('hashchange', heard);
        expect(followGuideTarget('#projects')).toBe(true);
        expect(window.location.hash).toBe('#projects');
        heard.mockClear();
        expect(followGuideTarget('#projects')).toBe(true);
        expect(heard).toHaveBeenCalledTimes(1);
        expect(followGuideTarget('javascript:alert(1)')).toBe(false);
        expect(followGuideTarget('https://example.com')).toBe(false);
        expect(window.location.hash).toBe('#projects');
        window.removeEventListener('hashchange', heard);
    });
});
