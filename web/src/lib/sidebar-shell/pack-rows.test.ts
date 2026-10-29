/** @vitest-environment jsdom */
import { flushSync, mount, unmount } from 'svelte';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import PackSection from './PackSection.svelte';
import { filledCells, levelOf } from '../pack-machines/pack-meter-math';
import { hostLightHtml } from './pack-light';
import { fitStats } from './pack-fit';
import type { PackPlan, PackRowPlan } from './plan';
import type { PackMachine } from '../pack-machines/pack-machines-store.svelte';

const SNAP = {
    load: { cores: 10, load_1: 5, memory_percent: 58.4, disk_percent: 40 },
    reserve: { level: 'in_use', cpu_pct: 30, mem_pct: 20, source: 'schedule' },
} as unknown as PackMachine['snapshot'];

function machine(over: Partial<PackMachine> & { host_key?: string | null } = {}): PackMachine {
    return {
        install_id: 'a', label: 'nostromo', is_self: true, is_master: true, paired: true, state: 'self', capabilities: [],
        specs: { model: 'Mac16,10', cores: 10, mem_total_gb: 16 }, snapshot: SNAP, age_seconds: 1, ...over,
    } as PackMachine;
}

const host = {
    StatusLed: { ledHtml: (o: { inner: string }) => `<span class="status-led" data-inner="${o.inner}" title="x"></span>` },
    SessionStatusSummary: {
        summaryHtml: (rows: unknown[]) => `<span class="status-led" data-inner="${rows.length ? 'working' : 'unknown'}" title="x"></span>`,
    },
};

function plan(density: string, machines: PackMachine[], rows: Array<{ host_key?: string; name: string; kind?: string }> = []): PackPlan {
    const prows: PackRowPlan[] = machines.map((m) => ({
        id: m.install_id, label: m.label, alpha: m.is_master, self: m.is_self, link: m.is_self ? null : 'linked', machine: m, off: false,
        lightHtml: hostLightHtml(m, rows as never, host),
    }));
    return {
        type: 'pack', key: 'pack', open: true, density, count: prows.length, rows: prows,
        heading: { toggle: 'group', key: 'pack', bandKind: 'reserved', expanded: true, bodyId: 'b', title: 't', label: 'pack',
            iconHtml: '', ledHtml: '', pickedIconHtml: '', rollupHtml: '' },
    };
}

let handle: ReturnType<typeof mount> | null = null;
function draw(p: PackPlan): HTMLElement {
    const target = document.body.appendChild(document.createElement('div'));
    handle = mount(PackSection, { target, props: { p } });
    flushSync();
    return target;
}
const observers = vi.fn();
beforeEach(() => {
    document.body.innerHTML = '';
    observers.mockClear();
    (globalThis as Record<string, unknown>).ResizeObserver = class { constructor() { observers(); } observe(): void {} disconnect(): void {} };
});
afterEach(() => { if (handle) unmount(handle); handle = null; });

describe('drawer pack rows', () => {
    it('the alpha row has the red wolf labelled Alpha, a non-alpha row has none, and the order is icon, wolf, light, name, stats', () => {
        const el = draw(plan('compact', [machine(), machine({ install_id: 'b', label: 'studio', is_self: false, is_master: false, state: 'connected', host_key: 'peer' })]));
        const rows = el.querySelectorAll('[data-pack-computer]');
        expect(rows.length).toBe(2);
        const wolf = rows[0]!.querySelector('[data-mark="alpha"]')!;
        expect(wolf.getAttribute('aria-label')).toBe('Alpha');
        expect(wolf.getAttribute('title')).toBe('Alpha');
        expect(rows[1]!.querySelector('[data-mark="alpha"]')).toBeNull();
        expect(rows[0]!.textContent).not.toMatch(/alpha/i);
        const order = [...rows[0]!.querySelector('.sb-pack-row__main')!.children].map((c) => c.className.split(' ')[0]);
        expect(order).toEqual(['pk-marks', 'sb-pack-row__wolf', 'sb-pack-row__light', 'sb-pack-row__name', 'sb-pack-row__stats']);
        expect(el.querySelectorAll('[title]').length, 'the wolf is the only tooltip').toBe(1);
    });

    it('compact shows three labeled whole percents, cpu from load over cores', () => {
        const el = draw(plan('compact', [machine()]));
        const stats = [...el.querySelectorAll('.sb-pack-stat')].map((s) => s.textContent);
        expect(stats).toEqual(['cpu50%', 'ram58%', '40%']);
        expect(el.querySelector('.pk-meter')).toBeNull();
    });

    it('one ResizeObserver per section, not one per row', () => {
        draw(plan('compact', [machine(), machine({ install_id: 'b', label: 'studio', is_self: false })]));
        expect(observers).toHaveBeenCalledTimes(1);
    });

    it('compact disk is an icon with the catalog name, not the word, and no tooltip', () => {
        const el = draw(plan('compact', [machine()]));
        const k = el.querySelectorAll('.sb-pack-stat')[2]!.querySelector('.sb-pack-stat__k')!;
        expect(k.getAttribute('role')).toBe('img');
        expect(k.getAttribute('aria-label')).toBe('disk');
        expect(k.querySelector('svg')).not.toBeNull();
        expect(k.textContent).toBe('');
        expect(k.hasAttribute('title')).toBe(false);
    });

    it('compact colors each percent with the Settings meter level: 49 green, 87 yellow, 95 red, unmeasured muted', () => {
        const snap = (cpu: number, mem: number, disk: number) => ({ ...SNAP, load: { cores: 10, load_1: cpu / 10, memory_percent: mem, disk_percent: disk } }) as PackMachine['snapshot'];
        const el = draw(plan('compact', [machine({ snapshot: snap(95, 49, 87) })]));
        const v = [...el.querySelectorAll('.sb-pack-stat__v')];
        expect(v.map((n) => n.textContent)).toEqual(['95%', '49%', '87%']);
        expect(v.map((n) => n.getAttribute('data-level'))).toEqual([levelOf(95), levelOf(49), levelOf(87)]);
        expect(v.map((n) => n.getAttribute('data-level'))).toEqual(['critical', 'normal', 'high']);
        expect(v.every((n) => n.tagName === 'SPAN' && !n.closest('b, strong'))).toBe(true);
        const none = draw(plan('compact', [machine({ install_id: 'n', snapshot: { ...SNAP, load: { cores: 10, load_1: null, memory_percent: null, disk_percent: null } } as PackMachine['snapshot'] })]));
        expect([...none.querySelectorAll('.sb-pack-stat__v')].map((n) => n.getAttribute('data-level'))).toEqual(['none', 'none', 'none']);
    });

    it('cozy shows three meters on a second line of their own, the name line carries none, and no third line', () => {
        const el = draw(plan('cozy', [machine({ label: 'sixteen-char-name' })]));
        const row = el.querySelector('[data-pack-computer]')!;
        const lines = [...row.children];
        expect(lines.length).toBe(2);
        expect(lines[0]!.className).toContain('sb-pack-row__main');
        expect(lines[0]!.querySelector('.pk-meter, .sb-pack-row__stats')).toBeNull();
        expect(lines[1]!.className).toContain('sb-pack-row__stats');
        expect(lines[1]!.querySelectorAll('.pk-meter').length).toBe(3);
        expect(row.querySelector('.sb-pack-row__meta')).toBeNull();
        expect(row.querySelector('.sb-pack-row__name')!.textContent).toBe('sixteen-char-name');
    });

    it('a meter draws its filled cells: 50% lights filledCells(50), 0% lights none, and the bar column is not a fixed width', () => {
        const el = draw(plan('cozy', [machine(), machine({ install_id: 'z', label: 'idle-box', snapshot: { ...SNAP, load: { cores: 10, load_1: 0, memory_percent: 0, disk_percent: 0 } } as PackMachine['snapshot'] })]));
        const lit = (m: Element) => m.querySelectorAll('.pk-meter__cell[data-on="1"]').length;
        const [busy, idle] = [...el.querySelectorAll('[data-pack-computer]')].map((r) => [...r.querySelectorAll('.pk-meter')]);
        expect(lit(busy![0]!)).toBe(filledCells(50));
        expect(lit(busy![0]!)).toBeGreaterThan(0);
        expect(busy!.map(lit)).toEqual([filledCells(50), filledCells(58.4), filledCells(40)]);
        expect(idle!.map(lit)).toEqual([0, 0, 0]);
        expect(busy![0]!.querySelectorAll('.pk-meter__cell[data-held="1"]').length, 'cpu shows the held-back zone').toBe(6);
        expect(busy![2]!.querySelectorAll('.pk-meter__cell[data-held="1"]').length, 'disk has no reserve').toBe(0);
    });

    it('detailed adds the second line: model, cores, memory and the reserve in force', () => {
        const el = draw(plan('detailed', [machine()]));
        expect([...el.querySelector('[data-pack-computer]')!.children].map((c) => c.className.split(' ')[0]), 'three lines')
            .toEqual(['sb-pack-row__main', 'sb-pack-row__stats', 'sb-pack-row__meta']);
        expect(el.querySelectorAll('.pk-meter').length).toBe(3);
        expect(el.querySelector('.sb-pack-row__meta')!.textContent).toBe('Mac16,10 10 cores 16 gb reserve in use 30% / 20%');
    });

    it('missing specs are left out, never printed as null', () => {
        const el = draw(plan('detailed', [machine({ specs: { model: null, cores: 4 } })]));
        const text = el.querySelector('.sb-pack-row__meta')!.textContent!;
        expect(text).toBe('4 cores reserve in use 30% / 20%');
        expect(text).not.toMatch(/null|undefined/);
    });

    it('no snapshot: no numbers or meters, the state word, and the row dims', () => {
        const el = draw(plan('cozy', [machine({ is_self: false, is_master: false, state: 'stale', snapshot: null })]));
        const row = el.querySelector('[data-pack-computer]')!;
        expect(row.getAttribute('data-host-state')).toBe('stale');
        expect(row.querySelector('.pk-meter')).toBeNull();
        expect(row.querySelector('.sb-pack-row__state')!.textContent).toBe('no answer lately');
        expect(row.textContent).not.toMatch(/\d%/);
    });
});

describe('the host light', () => {
    const agent = { name: 'x', status: 'working' };
    it('reads unknown when the computer\'s agents cannot be read, idle with none, and the roll-up otherwise', () => {
        const peer = machine({ is_self: false, state: 'connected', host_key: 'peer' });
        const light = (m: PackMachine, rows: object[]) => /data-inner="(\w+)"/.exec(hostLightHtml(m as never, rows as never, host))![1];
        expect(light(machine({ is_self: false, state: 'connected', host_key: null }), [agent]), 'no listing key').toBe('unknown');
        expect(light(machine({ is_self: false, state: 'stale', host_key: 'peer' }), [])).toBe('unknown');
        expect(light(peer, [{ ...agent, host_key: 'peer', host_state: 'down' }]), 'its rows say it is down').toBe('unknown');
        expect(light(peer, [])).toBe('idle');
        expect(light(peer, [{ ...agent, host_key: 'peer' }])).toBe('working');
        expect(light(machine(), [{ ...agent, host_key: 'peer' }]), 'this computer ignores a peer\'s agents').toBe('idle');
        expect(hostLightHtml(peer as never, [], host), 'the light carries no hover title').not.toMatch(/title=/);
    });
});

describe('fitStats (pure fit rule)', () => {
    const W = { cpu: 40, ram: 40, disk: 30 };
    it('shows all three when everything fits', () => {
        expect(fitStats(222, 100, W, 4)).toEqual({ show: { cpu: true, ram: true, disk: true }, truncate: false });
    });
    it('hides disk first', () => {
        expect(fitStats(221, 100, W, 4)).toEqual({ show: { cpu: true, ram: true, disk: false }, truncate: false });
    });
    it('hides ram second', () => {
        expect(fitStats(188, 100, W, 4)).toEqual({ show: { cpu: true, ram: true, disk: false }, truncate: false });
        expect(fitStats(187, 100, W, 4)).toEqual({ show: { cpu: true, ram: false, disk: false }, truncate: false });
    });
    it('never hides cpu: the name truncates instead', () => {
        expect(fitStats(144, 100, W, 4)).toEqual({ show: { cpu: true, ram: false, disk: false }, truncate: false });
        expect(fitStats(143, 100, W, 4)).toEqual({ show: { cpu: true, ram: false, disk: false }, truncate: true });
        expect(fitStats(0, 100, W, 4).show.cpu).toBe(true);
    });
});
