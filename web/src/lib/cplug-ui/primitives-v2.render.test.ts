/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import Renderer from './Renderer.svelte';
import { ApiError } from '../../opscenter/api/auth.svelte';
import type { Declared } from './validate';

const t = (key: string): string => key;
const DECLARED: Declared = { routes: ['save', 'nested', 'retry'], tools: ['run_check'] };

let mounted: ReturnType<typeof mount> | null = null;
afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
    vi.restoreAllMocks();
});

async function renderDoc(document_: unknown, run = vi.fn(async () => undefined)): Promise<{ root: HTMLElement; run: typeof run }> {
    const target = document.createElement('div');
    document.body.append(target);
    mounted = mount(Renderer, {
        target,
        props: { cplugId: 'v2-plug', name: 'V2 Plugin', document: document_, declared: DECLARED, t, run },
    });
    await tick();
    await tick();
    flushSync();
    return { root: target, run };
}

describe('Declarative UI v2 primitives (Feature 20b)', () => {
    test('form validates required fields, submits merged action payload + all control values, and isolates nested forms', async () => {
        const doc = {
            schema: 2,
            data: { initialHost: 'node-1', initialAuto: true },
            root: {
                type: 'column',
                children: [
                    {
                        type: 'form',
                        action: { call: 'route', route: 'save', payload: { source: 'panel' } },
                        submit_label: 'Apply',
                        children: [
                            { type: 'input', name: 'host', label: 'Host', value: { bind: '/initialHost' }, input_type: 'text', required: true },
                            { type: 'textarea', name: 'notes', label: 'Notes', rows: 4, required: true, placeholder: 'Add notes' },
                            { type: 'select', name: 'mode', label: 'Mode', options: ['fast', { value: 'deep', label: 'Deep' }] },
                            { type: 'toggle', name: 'auto', label: 'Auto sync', checked: { bind: '/initialAuto' }, tone: 'accent' },
                            {
                                type: 'form',
                                action: { call: 'tool', name: 'run_check', payload: { inner: true } },
                                submit_label: 'Check',
                                children: [
                                    { type: 'input', name: 'host', label: 'Inner Host', value: 'inner-1', required: true },
                                ],
                            },
                        ],
                    },
                ],
            },
        };

        const { root, run } = await renderDoc(doc);
        const forms = root.querySelectorAll<HTMLFormElement>('[data-cu="form"]');
        expect(forms).toHaveLength(2);
        const outerForm = forms[0]!;
        const innerForm = forms[1]!;

        outerForm.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
        await tick();
        flushSync();
        expect(run).not.toHaveBeenCalled();
        expect(outerForm.querySelector('.oc-form-field__error')?.textContent).toBe('cplug_ui.field_required');

        innerForm.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
        await tick();
        await tick();
        flushSync();
        expect(run).toHaveBeenCalledTimes(1);
        expect(run).toHaveBeenLastCalledWith({
            call: 'tool',
            name: 'run_check',
            payload: { inner: true, host: 'inner-1' },
        });

        const notes = outerForm.querySelector<HTMLTextAreaElement>('textarea[name="notes"]')!;
        expect(notes.rows).toBe(4);
        notes.value = 'ready';
        notes.dispatchEvent(new Event('input', { bubbles: true }));

        const select = outerForm.querySelector<HTMLSelectElement>('select[name="mode"]')!;
        expect(select.value).toBe('fast');
        select.value = 'deep';
        select.dispatchEvent(new Event('change', { bubbles: true }));

        const toggleBtn = outerForm.querySelector<HTMLButtonElement>('[data-cu="toggle"] [role="switch"]')!;
        expect(toggleBtn.getAttribute('aria-checked')).toBe('true');
        toggleBtn.click();
        flushSync();
        expect(toggleBtn.getAttribute('aria-checked')).toBe('false');

        outerForm.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
        await tick();
        await tick();
        flushSync();
        expect(run).toHaveBeenCalledTimes(2);
        expect(run).toHaveBeenLastCalledWith({
            call: 'route',
            route: 'save',
            payload: { source: 'panel', host: 'node-1', notes: 'ready', mode: 'deep', auto: false },
        });
    });

    test('form surfaces 409 cplug_not_running and generic errors cleanly', async () => {
        const run = vi.fn()
            .mockRejectedValueOnce(new ApiError('offline', 409, 'cplug_not_running'))
            .mockRejectedValueOnce(new Error('boom'));
        const { root } = await renderDoc({
            schema: 2,
            root: {
                type: 'form',
                action: { call: 'route', route: 'save' },
                children: [{ type: 'input', name: 'k', label: 'Key', value: 'v' }],
            },
        }, run);
        const form = root.querySelector('form')!;
        form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
        await tick();
        await tick();
        flushSync();
        expect(root.querySelector('.cu-form__line')?.textContent).toBe('cplug_ui.not_running');

        form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
        await tick();
        await tick();
        flushSync();
        expect(root.querySelector('.cu-form__line')?.textContent).toBe('cplug_ui.action_failed');
    });

    test('tabs activate node.active by default, switch panels, and preserve form state in hidden tabs', async () => {
        const doc = {
            schema: 2,
            root: {
                type: 'form',
                action: { call: 'route', route: 'save' },
                children: [
                    {
                        type: 'tabs',
                        active: 'second',
                        items: [
                            { id: 'first', label: 'First', content: { type: 'input', name: 'a', label: 'A', value: 'alpha' } },
                            { id: 'second', label: 'Second', children: [{ type: 'input', name: 'b', label: 'B', value: 'beta' }] },
                        ],
                    },
                ],
            },
        };
        const { root, run } = await renderDoc(doc);
        const tabs = root.querySelectorAll<HTMLButtonElement>('[role="tab"]');
        const panels = root.querySelectorAll<HTMLElement>('[role="tabpanel"]');
        expect(tabs[0]?.getAttribute('aria-selected')).toBe('false');
        expect(tabs[1]?.getAttribute('aria-selected')).toBe('true');
        expect(panels[0]?.hidden).toBe(true);
        expect(panels[1]?.hidden).toBe(false);

        const inputB = root.querySelector<HTMLInputElement>('input[name="b"]')!;
        inputB.value = 'beta-edited';
        inputB.dispatchEvent(new Event('input', { bubbles: true }));

        tabs[0]!.click();
        flushSync();
        expect(panels[0]?.hidden).toBe(false);
        expect(panels[1]?.hidden).toBe(true);

        root.querySelector('form')!.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
        await tick();
        await tick();
        flushSync();
        expect(run).toHaveBeenCalledWith({
            call: 'route',
            route: 'save',
            payload: { a: 'alpha', b: 'beta-edited' },
        });
    });

    test('code renders plain text (never HTML) and copies to clipboard', async () => {
        const writeText = vi.fn(async () => undefined);
        Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });

        const { root } = await renderDoc({
            schema: 2,
            root: { type: 'code', value: '<script>alert(1)</script>', language: 'html' },
        });
        const codeNode = root.querySelector('[data-cu="code"]')!;
        expect(codeNode.getAttribute('data-language')).toBe('html');
        expect(codeNode.querySelector('script')).toBeNull();
        expect(codeNode.querySelector('.cu-code__text')?.textContent).toBe('<script>alert(1)</script>');

        const copyBtn = codeNode.querySelector<HTMLButtonElement>('button')!;
        expect(copyBtn.textContent?.trim()).toBe('cplug_ui.copy');
        copyBtn.click();
        await tick();
        await tick();
        flushSync();
        expect(writeText).toHaveBeenCalledExactlyOnceWith('<script>alert(1)</script>');
        expect(copyBtn.textContent?.trim()).toBe('cplug_ui.copied');
    });

    test('markdown_safe renders CommonMark AST safely with zero <a> tags and refuses unsafe { bind } values at render time', async () => {
        const safeMd = [
            '# Title',
            '',
            'Paragraph with **bold**, *em*, `code`, and [docs](readme.md).',
            '',
            '> Quoted line',
            '',
            '- Item one',
            '- Item two',
            '',
            '---',
            '',
            '```ts',
            'const x = 1;',
            '```',
        ].join('\n');

        const { root } = await renderDoc({
            schema: 2,
            data: {
                safeInline: '**bound** with [link](readme.md)',
                evilScript: '<script>alert(1)</script>',
                evilImg: '<img src=x onerror=alert(1)>',
            },
            root: {
                type: 'column',
                children: [
                    { type: 'markdown_safe', value: safeMd },
                    { type: 'markdown_safe', value: { bind: '/safeInline' } },
                    { type: 'markdown_safe', value: { bind: '/evilScript' } },
                    { type: 'markdown_safe', value: { bind: '/evilImg' } },
                ],
            },
        });

        const nodes = root.querySelectorAll('[data-cu="markdown_safe"]');
        expect(nodes).toHaveLength(4);
        const good = nodes[0]!;
        expect(good.querySelector('h1.cu-md__h')?.textContent).toBe('Title');
        expect(good.querySelector('strong.cu-md__strong')?.textContent).toBe('bold');
        expect(good.querySelector('em.cu-md__em')?.textContent).toBe('em');
        expect(good.querySelector('code.cu-md__code')?.textContent).toBe('code');
        expect(good.querySelector('span.cu-md__link')?.textContent).toBe('docs');
        expect(good.querySelector('a')).toBeNull();
        expect(good.querySelector('blockquote.cu-md__quote')?.textContent).toContain('Quoted line');
        expect(good.querySelectorAll('ul.cu-md__list > li.cu-md__item')).toHaveLength(2);
        expect(good.querySelector('hr.cu-md__hr')).not.toBeNull();
        expect(good.querySelector('pre.cu-md__pre')?.textContent).toBe('const x = 1;');

        const boundGood = nodes[1]!;
        expect(boundGood.querySelector('strong.cu-md__strong')?.textContent).toBe('bound');
        expect(boundGood.querySelector('span.cu-md__link')?.textContent).toBe('link');
        expect(boundGood.querySelector('a')).toBeNull();

        for (const refused of [nodes[2]!, nodes[3]!]) {
            expect(refused.querySelector('script')).toBeNull();
            expect(refused.querySelector('a')).toBeNull();
            expect(refused.querySelector('.cu-md__refused')?.textContent).toBe('cplug_ui.could_not_draw');
        }
    });

    test('progress, empty_state, and sparkline render accurately across tones and edge cases', async () => {
        const { root, run } = await renderDoc({
            schema: 2,
            root: {
                type: 'column',
                children: [
                    { type: 'progress', label: 'Syncing', value: 25, max: 50, tone: 'accent' },
                    { type: 'progress', label: 'Scanning', indeterminate: true, tone: 'warn' },
                    { type: 'empty_state', title: 'No jobs', description: 'Start a job', tone: 'warn', action: { call: 'route', route: 'retry' } },
                    { type: 'sparkline', values: [1, 4, 2, 8], label: 'Latency', tone: 'accent' },
                    { type: 'sparkline', values: [5] },
                    { type: 'sparkline', values: [3, 3, 3] },
                    { type: 'sparkline', values: [] },
                ],
            },
        });

        const bars = root.querySelectorAll('[role="progressbar"]');
        expect(bars[0]?.getAttribute('aria-valuenow')).toBe('25');
        expect(bars[0]?.getAttribute('aria-valuemax')).toBe('50');
        expect(root.querySelector('.cu-progress__pct')?.textContent).toBe('50%');
        expect((bars[0]?.querySelector('.cu-progress__fill') as HTMLElement).style.width).toBe('50%');
        expect(bars[1]?.getAttribute('aria-valuenow')).toBeNull();
        expect(bars[1]?.querySelector('.cu-progress__fill--indeterminate')).not.toBeNull();

        const empty = root.querySelector('[data-cu="empty_state"] .oc-state')!;
        expect(empty.getAttribute('data-state')).toBe('warn');
        empty.querySelector<HTMLButtonElement>('button')!.click();
        await tick();
        flushSync();
        expect(run).toHaveBeenCalledExactlyOnceWith({ call: 'route', route: 'retry' });

        const sparks = root.querySelectorAll('[data-cu="sparkline"]');
        expect(sparks).toHaveLength(4);
        for (const sp of sparks) {
            const pts = sp.querySelector('polyline')?.getAttribute('points') ?? '';
            expect(pts).not.toContain('NaN');
        }
        expect(sparks[0]?.querySelector('polyline')?.getAttribute('points')?.split(' ')).toHaveLength(4);
        expect(sparks[1]?.querySelector('polyline')?.getAttribute('points')).toBe('2.00,14.00 118.00,14.00');
        expect(sparks[3]?.querySelector('polyline')).toBeNull();
    });

    test('clicking submit button on valid nested Form stops propagation and does not submit valid ancestor Form', async () => {
        const doc = {
            schema: 2,
            root: {
                type: 'form',
                action: { call: 'route', route: 'save', payload: { scope: 'outer' } },
                submit_label: 'Save Outer',
                children: [
                    { type: 'input', name: 'x', label: 'Outer X', value: 'outer-val', required: true },
                    {
                        type: 'form',
                        action: { call: 'route', route: 'nested', payload: { scope: 'inner' } },
                        submit_label: 'Save Inner',
                        children: [
                            { type: 'input', name: 'x', label: 'Inner X', value: 'inner-val', required: true },
                        ],
                    },
                ],
            },
        };

        const { root, run } = await renderDoc(doc);
        const forms = root.querySelectorAll<HTMLFormElement>('[data-cu="form"]');
        expect(forms).toHaveLength(2);
        const innerBtn = forms[1]!.querySelector<HTMLButtonElement>('button[type="submit"]')!;
        innerBtn.click();
        await tick();
        await tick();
        flushSync();

        expect(run).toHaveBeenCalledTimes(1);
        expect(run).toHaveBeenCalledWith({
            call: 'route',
            route: 'nested',
            payload: { scope: 'inner', x: 'inner-val' },
        });
    });

    test('sparkline handles extreme float ranges without NaN overflow', async () => {
        const { root } = await renderDoc({
            schema: 2,
            root: {
                type: 'sparkline',
                values: [-1e308, 0, 1e308],
            },
        });
        const pts = root.querySelector('[data-cu="sparkline"] polyline')?.getAttribute('points') ?? '';
        expect(pts).not.toContain('NaN');
        expect(pts).not.toContain('Infinity');
        expect(pts).toBe('2.00,25.00 60.00,14.00 118.00,3.00');
    });
});
