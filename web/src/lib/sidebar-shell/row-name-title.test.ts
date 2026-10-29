/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { revealCutOffText } from '../tooltip/cut-off-reveal';
import type { RowHost } from './row-host';
import { buildRowPlan } from './row-plan';

const LONG = 'a very long session name that the drawer will certainly truncate with an ellipsis';

type NameAttrs = { name: { attrs: Record<string, string | undefined> } };
const attrsOf = (plan: unknown): Record<string, string | undefined> => (plan as NameAttrs).name.attrs;

describe('a drawer row name carries no tooltip, cut off or not (Alex (Example-owner), 2026-10-01)', () => {
    for (const density of ['compact', 'cozy', 'detailed']) {
        it(`session row, ${density}`, () => {
            const plan = buildRowPlan({ name: LONG, status: 'idle', agent_family: 'claude' }, density, undefined, null, {} as RowHost);
            expect(attrsOf(plan).title).toBeUndefined();
            expect(attrsOf(plan)['data-tooltip']).toBeUndefined();
        });
    }
    it('browser row carries no title either', () => {
        const plan = buildRowPlan({ name: 'b1', label: LONG, kind: 'browser', status: 'live' }, 'compact', undefined, null, {} as RowHost);
        expect(attrsOf(plan).title).toBeUndefined();
    });
});

describe('a cut-off row name reveals its words, a name that fits does not (Joe (ccsliinc), 2026-10-14)', () => {
    afterEach(() => {
        vi.restoreAllMocks();
        document.body.innerHTML = '';
    });
    function nameEl(scroll: number, client: number): HTMLElement {
        const plan = buildRowPlan({ name: LONG, status: 'idle', agent_family: 'claude' }, 'compact', undefined, null, {} as RowHost);
        const el = document.createElement('span');
        for (const [k, v] of Object.entries(attrsOf(plan))) if (v !== undefined) el.setAttribute(k, v);
        el.textContent = LONG;
        Object.defineProperty(el, 'scrollWidth', { value: scroll });
        Object.defineProperty(el, 'clientWidth', { value: client });
        document.body.appendChild(el);
        const real = window.getComputedStyle.bind(window);
        vi.spyOn(window, 'getComputedStyle').mockImplementation((n: Element) => {
            const cs = real(n);
            return n === el ? new Proxy(cs, { get: (t, k) => (k === 'textOverflow' ? 'ellipsis' : Reflect.get(t, k)) }) : cs;
        });
        return el;
    }
    it('reveals when cut off, and the plan itself still carries nothing', () => {
        const el = nameEl(500, 120);
        expect(el.hasAttribute('data-tooltip')).toBe(false);
        revealCutOffText(el);
        expect(el.getAttribute('data-tooltip')).toBe(LONG);
    });
    it('reveals nothing when the name fits', () => {
        const el = nameEl(120, 120);
        revealCutOffText(el);
        expect(el.hasAttribute('data-tooltip')).toBe(false);
    });
});
