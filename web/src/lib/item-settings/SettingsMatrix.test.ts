/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import SettingsForm from './SettingsForm.svelte';
import { validateManifest } from '../../opscenter/widgets/validate';
import type { WidgetSettingsSchema } from '../../opscenter/widgets/types';
import { gridFields, gridMatrix } from '../beast-mode/grid-model';
import { RULES } from '../beast-mode/grid-fixture';

const t = (key: string): string => key;

const SCHEMA: WidgetSettingsSchema = {
    version: 1,
    fields: {
        aOff: { kind: 'boolean', labelKey: 'x.row.a', default: true },
        aOn: { kind: 'boolean', labelKey: 'x.row.a', default: true },
        bOff: { kind: 'boolean', labelKey: 'x.row.b', default: false },
        bOn: { kind: 'boolean', labelKey: 'x.row.b', default: true },
    },
    groups: [{
        labelKey: 'x.group', fields: ['aOff', 'aOn', 'bOff', 'bOn'],
        matrix: {
            columns: ['x.col.off', 'x.col.on'],
            rows: [
                { labelKey: 'x.row.a', fields: ['aOff', 'aOn'] },
                { labelKey: 'x.row.b', hintKey: 'x.row.b_help', fields: ['bOff', 'bOn'], confirm: { bOff: 'x.row.b_confirm' } },
                { labelKey: 'x.row.never', locked: true },
            ],
        },
    }],
};

let handle: Record<string, unknown> | null = null;
afterEach(() => {
    if (handle) unmount(handle);
    handle = null;
    document.body.innerHTML = '';
});

function draw(values: Record<string, boolean>, changes: [string, unknown][]): HTMLElement {
    const target = document.createElement('div');
    document.body.append(target);
    handle = mount(SettingsForm, { target, props: { schema: SCHEMA, values, t, onChange: (key: string, value: unknown) => changes.push([key, value]) } }) as Record<string, unknown>;
    flushSync();
    return target;
}

describe('the settings mode matrix', () => {
    test('columns, rows, defaults and stored values, and a locked row has no box', () => {
        const target = draw({ aOn: false }, []);
        const table = target.querySelector('[data-settings-matrix]')!;
        expect([...table.querySelectorAll('thead [data-matrix-column]')].map((c) => c.textContent)).toEqual(['x.col.off', 'x.col.on']);
        const state = (key: string): string | null => table.querySelector(`[data-setting="${key}"] [role="checkbox"]`)!.getAttribute('aria-checked');
        expect([state('aOff'), state('aOn'), state('bOff'), state('bOn')]).toEqual(['true', 'false', 'false', 'true']);
        const locked = table.querySelector('[data-matrix-row="x.row.never"]')!;
        expect(locked.getAttribute('data-locked')).toBe('1');
        expect(locked.querySelector('[role="checkbox"]')).toBeNull();
        expect(locked.textContent).toContain('item_settings.matrix.locked');
        expect(table.querySelector('[data-setting="bOn"] [role="checkbox"]')!.getAttribute('aria-label')).toBe('x.row.b, x.col.on');
        expect(target.querySelector('[data-setting="aOff"][data-kind]'), 'a matrix group draws no plain rows').toBeNull();
    });

    test('every combination of one row is reachable: a box reports its own key and the other state', () => {
        for (const [off, on] of [[false, false], [true, false], [false, true], [true, true]] as const) {
            const changes: [string, unknown][] = [];
            const target = draw({ bOff: off, bOn: on }, changes);
            (target.querySelector('[data-setting="bOff"] [role="checkbox"]') as HTMLElement).click();
            flushSync();
            if (!off) (target.querySelector('[data-matrix-ask-confirm]') as HTMLElement).click();
            (target.querySelector('[data-setting="bOn"] [role="checkbox"]') as HTMLElement).click();
            expect(changes).toEqual([['bOff', !off], ['bOn', !on]]);
            unmount(handle!);
            handle = null;
            document.body.innerHTML = '';
        }
    });

    test('a cell that asks first saves nothing until the owner confirms, cancel saves nothing, and unticking never asks', () => {
        const changes: [string, unknown][] = [];
        const target = draw({ bOff: false }, changes);
        const box = (): HTMLElement => target.querySelector('[data-setting="bOff"] [role="checkbox"]') as HTMLElement;
        box().click();
        flushSync();
        const ask = target.querySelector('[data-matrix-ask="bOff"]')!;
        expect(ask.textContent).toContain('x.row.b_confirm');
        expect(ask.querySelector('[data-matrix-ask-confirm][data-btn="danger"]')).not.toBeNull();
        expect(changes, 'the tick waits on the confirm').toEqual([]);
        (target.querySelector('[data-matrix-ask-cancel]') as HTMLElement).click();
        flushSync();
        expect(target.querySelector('[data-matrix-ask]')).toBeNull();
        expect(changes, 'cancel saves nothing').toEqual([]);
        box().click();
        flushSync();
        (target.querySelector('[data-matrix-ask-confirm]') as HTMLElement).click();
        flushSync();
        expect(changes).toEqual([['bOff', true]]);
        unmount(handle!);
        handle = null;
        document.body.innerHTML = '';
        const off: [string, unknown][] = [];
        const ticked = draw({ bOff: true }, off);
        (ticked.querySelector('[data-setting="bOff"] [role="checkbox"]') as HTMLElement).click();
        flushSync();
        expect(ticked.querySelector('[data-matrix-ask]')).toBeNull();
        expect(off).toEqual([['bOff', false]]);
        (ticked.querySelector('[data-setting="aOff"] [role="checkbox"]') as HTMLElement).click();
        expect(off, 'a cell with no confirm saves at once').toEqual([['bOff', false], ['aOff', false]]);
    });

    test('the beast mode grid asks before each beast off auto-approve box', () => {
        const rows = gridMatrix(RULES).rows;
        expect(rows.flatMap((r) => Object.keys(r.confirm ?? {})).sort()).toEqual(['agentWritesOff', 'claudePermissionOff', 'codexApprovalOff']);
    });

    test('the validator accepts the beast mode grid and refuses a malformed matrix', () => {
        const base = (settings: unknown): unknown => ({
            id: 'acme.grid', version: '1.0.0', titleKey: 'widgets.acme.grid', icon: 'grid', iconTone: 'oc-cyan', category: 'tools',
            type: 'tool', instancing: 'singleton', canvases: ['home'], bounds: { minW: 200, minH: 60, maxW: 900 },
            fits: { min: { w: 2, h: 1 }, sizes: ['wide'], anySize: false },
            densities: { width: [{ name: 'narrow', min: 0 }], height: [{ name: 'line', min: 0 }] }, settings, capabilities: [],
        });
        const beastSchema = { version: 1, fields: gridFields(RULES), groups: [{ labelKey: 'beast.settings.group.grid', fields: Object.keys(gridFields(RULES)), matrix: gridMatrix(RULES) }] };
        expect(validateManifest(base(beastSchema)).ok).toBe(true);
        expect(validateManifest(base(SCHEMA)).ok).toBe(true);
        const broken = (mutate: (m: any) => void): boolean => {
            const copy = JSON.parse(JSON.stringify(SCHEMA));
            mutate(copy.groups[0].matrix);
            return validateManifest(base(copy)).ok;
        };
        expect(broken((m) => { m.columns = ['x.col.off']; })).toBe(false);
        expect(broken((m) => { m.rows[0].fields = ['aOff']; })).toBe(false);
        expect(broken((m) => { m.rows[2].fields = ['aOff', 'aOn']; })).toBe(false);
        expect(broken((m) => { m.rows[1].fields = ['bOn', 'bOff']; })).toBe(false);
        expect(broken((m) => { m.rows.pop(); m.rows.pop(); })).toBe(false);
        expect(broken((m) => { m.extra = 1; })).toBe(false);
        expect(broken((m) => { m.rows[1].confirm = { aOff: 'x.c' }; })).toBe(false);
        expect(broken((m) => { m.rows[1].confirm = { bOff: 'Not A Key' }; })).toBe(false);
        expect(broken((m) => { m.rows[2].confirm = { bOff: 'x.c' }; })).toBe(false);
    });
});
