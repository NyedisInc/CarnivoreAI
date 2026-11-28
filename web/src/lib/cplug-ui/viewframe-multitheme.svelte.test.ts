/** @vitest-environment jsdom */
import { flushSync, mount, tick, unmount } from 'svelte';
import { afterEach, describe, expect, test, vi } from 'vitest';
import { themeValuesFromOc } from './frame-theme';
import ViewFrame from './ViewFrame.svelte';

const mounted: Array<() => void> = [];

afterEach(() => {
    while (mounted.length > 0) mounted.pop()?.();
    document.body.innerHTML = '';
    vi.restoreAllMocks();
});

describe('ViewFrame multi-theme & viewSrc extensions', () => {
    test('themeValuesFromOc maps safe --oc-* vars and legacy unprefixed tokens while rejecting unsafe urls', () => {
        const values = themeValuesFromOc(
            {
                '--oc-ground-page': '#02161e',
                '--oc-text-primary': 'rgb(203, 214, 217)',
                '--oc-cyan': 'url(https://evil.example/x.png)',
                '--oc-font': "'JetBrains Mono', monospace",
            },
            'ui-monospace',
        );
        expect(values['--oc-ground-page']).toBe('#02161e');
        expect(values['ground-page']).toBe('#02161e');
        expect(values['text-primary']).toBe('rgb(203, 214, 217)');
        expect(values['--oc-cyan']).toBeUndefined();
        expect(values['cyan']).toBeUndefined();
        expect(values['font-mono']).toBe("'JetBrains Mono', monospace");
    });

    test('ViewFrame uses provided viewSrc and themeValues without calling fetch or mutating document.body', async () => {
        const fetchSpy = vi.spyOn(globalThis, 'fetch');
        const host = document.createElement('div');
        document.body.append(host);

        const plugin = {
            cplugId: 'studio-sample',
            name: 'StudioSample',
            unverified: true,
            declared: { routes: [], tools: [] },
        };

        let currentTheme = $state(
            themeValuesFromOc({
                '--oc-ground-page': '#02161e',
                '--oc-text-primary': '#cbd6d9',
            }),
        );

        const instance = mount(ViewFrame, {
            target: host,
            props: {
                plugin,
                view: 'studio',
                surface: 'panel',
                viewSrc: 'https://preview.example.com/signed-view',
                get themeValues() {
                    return currentTheme;
                },
                t: (k: string) => k,
            },
        });
        mounted.push(() => unmount(instance));

        await tick();
        flushSync();

        expect(fetchSpy).not.toHaveBeenCalled();

        const frame = host.querySelector('iframe') as HTMLIFrameElement;
        expect(frame).toBeTruthy();
        expect(frame.getAttribute('src')).toBe('https://preview.example.com/signed-view');

        const posted: Array<Record<string, unknown>> = [];
        vi.spyOn(frame.contentWindow!, 'postMessage').mockImplementation((msg: unknown) => {
            posted.push(msg as Record<string, unknown>);
        });
        frame.dispatchEvent(new Event('load'));

        const initMsg = posted.find((m) => m.verb === 'init') as
            | { theme?: Record<string, string> }
            | undefined;
        expect(initMsg?.theme?.['--oc-ground-page']).toBe('#02161e');

        currentTheme = themeValuesFromOc({
            '--oc-ground-page': '#001100',
            '--oc-text-primary': '#33ff66',
        });
        await tick();
        flushSync();

        const themeUpdate = posted.find(
            (m) => m.verb === 'theme' && (m.theme as Record<string, string>)?.['--oc-ground-page'] === '#001100',
        );
        expect(themeUpdate).toBeTruthy();
        expect(document.body.getAttribute('data-theme')).toBeNull();
    });

    test('ViewFrame allows host-driven viewSrc ticket updates across reloads while still blocking in-iframe self-navigation', async () => {
        const host = document.createElement('div');
        document.body.append(host);

        const plugin = {
            cplugId: 'studio-sample',
            name: 'StudioSample',
            unverified: true,
            installKey: 'stu_1',
            declared: { routes: [], tools: [] },
        };

        let currentSrc = $state('https://preview.example.com/ticket1');
        const currentTheme = themeValuesFromOc({
            '--oc-ground-page': '#02161e',
            '--oc-text-primary': '#cbd6d9',
        });

        const instance = mount(ViewFrame, {
            target: host,
            props: {
                plugin,
                view: 'studio',
                surface: 'panel',
                get viewSrc() {
                    return currentSrc;
                },
                themeValues: currentTheme,
                t: (k: string) => k,
            },
        });
        mounted.push(() => unmount(instance));

        await tick();
        flushSync();

        const loadAndCollectInit = (expectedSrc: string): { frame: HTMLIFrameElement; nonce: string } => {
            const frame = host.querySelector('iframe') as HTMLIFrameElement;
            expect(frame).toBeTruthy();
            expect(frame.getAttribute('src')).toBe(expectedSrc);
            const posted: Array<Record<string, unknown>> = [];
            vi.spyOn(frame.contentWindow!, 'postMessage').mockImplementation((msg: unknown) => {
                posted.push(msg as Record<string, unknown>);
            });
            frame.dispatchEvent(new Event('load'));
            flushSync();
            const initMsg = posted.find((m) => m.verb === 'init');
            expect(initMsg).toBeTruthy();
            expect(host.textContent).not.toContain('cplug_ui.could_not_draw');
            return { frame, nonce: String(initMsg?.nonce ?? '') };
        };

        const first = loadAndCollectInit('https://preview.example.com/ticket1');

        currentSrc = 'https://preview.example.com/ticket2';
        await tick();
        flushSync();
        const second = loadAndCollectInit('https://preview.example.com/ticket2');
        expect(second.nonce).not.toBe(first.nonce);

        currentSrc = 'https://preview.example.com/ticket3';
        await tick();
        flushSync();
        const third = loadAndCollectInit('https://preview.example.com/ticket3');
        expect(third.nonce).not.toBe(second.nonce);

        third.frame.dispatchEvent(new Event('load'));
        await tick();
        flushSync();
        expect(host.querySelector('iframe')).toBeNull();
        expect(host.textContent).toContain('cplug_ui.could_not_draw');
    });
});
