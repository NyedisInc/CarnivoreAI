import { describe, expect, it } from 'vitest';
import type { LabHost, LabSize } from '../sdk/widget-lab';
import { captureRequest, defaultSize, filterGroups, uncheckedCount, sizeChoices, sizeLine, sizesToDraw, treeGroups, frameVerdict, widgetOf, widgetVerdict, distinctWidgets, type FitTable } from './lab-model';

const size = (name: string, w = 100, h: number | null = 50): LabSize => ({ name, w, h, viewport: 1600, declared: false, floor: name === 's' });
const host = (sizes: LabSize[]): LabHost => ({ zone: 'home', supported: true, refusal: null, sizes });

describe('defaultSize', () => {
  it('opens on the middle size when the host publishes one', () => {
    expect(defaultSize(host([size('s'), size('m'), size('l')]))?.name).toBe('m');
  });

  it('opens on the first size when there is no middle one, and on nothing for a host with none', () => {
    expect(defaultSize(host([size('s'), size('l')]))?.name).toBe('s');
    expect(defaultSize(host([]))).toBeNull();
  });
});

describe('sizeLine', () => {
  it('reads name and box, auto for a content-decided height', () => {
    expect(sizeLine(size('m', 384, 256))).toBe('m 384 x 256');
    expect(sizeLine(size('phone', 358, null))).toBe('phone 358 x auto');
  });
});

describe('captureRequest', () => {
  const draw = { widget: 'core.notes', host: 'home', size: 'm', theme: 'carnivore', fixture: 'data' as const };

  it('asks for the state on show, with no scenario key when none is applied', () => {
    expect(captureRequest(draw, null)).toEqual({ ...draw, state: 'normal' });
    expect(captureRequest(draw, null, 'menu')).toEqual({ ...draw, state: 'menu' });
  });

  it('carries the applied scenario text', () => {
    expect(captureRequest(draw, '{"GET /x": 1}').scenario).toBe('{"GET /x": 1}');
  });
});

describe('the fit table', () => {
  const row = (over: Partial<import('./lab-model').FitRow> = {}): import('./lab-model').FitRow => ({
    widget: 'core.notes', ok: true, determined: true, failures: 0,
    cells: {
      'home/m': { verdict: 'pass', red: false, draws: 8, reasons: [] },
      'home/s': { verdict: 'fail', red: true, draws: 8, reasons: ['overflow'] },
      'home/l': { verdict: 'fail', red: false, draws: 8, reasons: ['console error'] },
      'terminal/m': { verdict: 'unsupported', red: false, draws: 0, reasons: [] },
    },
    ...over,
  });

  it('lists columns host by host in the file order', async () => {
    const { fitColumns } = await import('./lab-model');
    const table = { schema: 1, generated_at: '', counts: { pass: 0, fail: 0, unsupported: 0 }, widgets: [], hosts: { home: ['s', 'm'], drawer: ['glance'] } };
    expect(fitColumns(table).map((c) => c.key)).toEqual(['home/s', 'home/m', 'drawer/glance']);
  });

  it('reads clipping as red, other failures as fail, and a missing or unsupported cell as unsupported', async () => {
    const { cellState } = await import('./lab-model');
    expect(cellState(row(), 'home/m')).toBe('pass');
    expect(cellState(row(), 'home/s')).toBe('red');
    expect(cellState(row(), 'home/l')).toBe('fail');
    expect(cellState(row(), 'terminal/m')).toBe('unsupported');
    expect(cellState(row(), 'drawer/glance')).toBe('unsupported');
  });

  it('never reads a row that could not be determined as a pass', async () => {
    const { cellState } = await import('./lab-model');
    expect(cellState(row({ determined: false }), 'home/m')).toBe('fail');
  });
});

describe('the tree and the size choices', () => {
  const widgets = [
    { key: 'core.notes', title: 'notes', category: 'tools' },
    { key: 'core.analytics:cost', title: 'analytics / cost', category: 'monitoring' },
    { key: 'core.analytics:load', title: 'analytics / load', category: 'monitoring' },
    { key: 'x.stray', title: 'stray', category: '' },
  ];

  it('groups by the manifest category in the drawer order, drops empty categories and puts an uncategorized widget last', () => {
    const groups = treeGroups(widgets, (id) => id.toUpperCase(), ['overview', 'monitoring', 'tools']);
    expect(groups.map((g) => g.id)).toEqual(['monitoring', 'tools', 'other']);
    expect(groups[0]!.label).toBe('MONITORING');
    expect(groups[0]!.leaves.map((l) => l.label)).toEqual(['analytics / cost', 'analytics / load']);
    expect(groups[1]!.leaves).toEqual([{ key: 'core.notes', label: 'notes' }]);
  });

  const table = (cells: Record<string, { verdict: 'pass' | 'fail' | 'unsupported'; red: boolean }>, determined = true): FitTable => ({
    schema: 1, generated_at: 'x', hosts: {}, counts: { pass: 0, fail: 0, unsupported: 0 },
    widgets: [{ widget: 'w', ok: true, determined, failures: 0, cells: Object.fromEntries(Object.entries(cells).map(([k, v]) => [k, { ...v, draws: 1, reasons: [] }])) }],
  });

  it('reads a verdict: any fail or clip fails, all pass passes, nothing drawn or no record is none, undetermined fails', () => {
    expect(widgetVerdict(null, 'w')).toBe('none');
    expect(widgetVerdict(table({ a: { verdict: 'pass', red: false } }), 'x')).toBe('none');
    expect(widgetVerdict(table({ a: { verdict: 'pass', red: false }, b: { verdict: 'unsupported', red: false } }), 'w')).toBe('pass');
    expect(widgetVerdict(table({ a: { verdict: 'pass', red: false }, b: { verdict: 'fail', red: true } }), 'w')).toBe('fail');
    expect(widgetVerdict(table({ a: { verdict: 'unsupported', red: false } }), 'w')).toBe('none');
    expect(widgetVerdict(table({}, false), 'w')).toBe('fail');
  });

  const host = (sizes: string[], supported = true): LabHost => ({
    zone: 'home', supported, refusal: null, sizes: sizes.map((name) => ({ name, w: 1, h: 1, viewport: 1, declared: false, floor: false })),
  });

  it('offers the union of declared hosts\' sizes and draws the picked ones, falling back to the default so a host never opens empty', () => {
    expect(sizeChoices([host(['s', 'm']), host(['m', 'l']), host(['x'], false)])).toEqual(['s', 'm', 'l']);
    expect(sizesToDraw(host(['s', 'm', 'l']), ['l', 's']).map((s) => s.name)).toEqual(['s', 'l']);
    expect(sizesToDraw(host(['s', 'm', 'l']), ['phone']).map((s) => s.name)).toEqual(['m']);
    expect(sizesToDraw(host([]), ['m'])).toEqual([]);
  });
});

describe('the result filter', () => {
  const leaf = (key: string) => ({ key, label: key });
  const groups = [{ id: 'g', label: 'g', leaves: [leaf('core.notes'), leaf('core.gone'), leaf('core.never')] }];
  const table = { schema: 1, generated_at: '', counts: { pass: 0, fail: 0, unsupported: 0 }, hosts: {}, widgets: [
    { widget: 'core.notes', ok: true, determined: true, failures: 0, cells: { 'home/m': { verdict: 'pass', red: false, draws: 1, reasons: [] } } },
    { widget: 'core.gone', ok: false, determined: false, failures: 1, cells: {} },
  ] } as FitTable;

  it('keeps all, only the failing, or only the widgets no run has judged', () => {
    const keys = (result: 'all' | 'failing' | 'unchecked') => filterGroups(groups, '', result, table).flatMap((one) => one.leaves.map((l) => l.key));
    expect(keys('all')).toEqual(['core.notes', 'core.gone', 'core.never']);
    expect(keys('failing')).toEqual(['core.gone']);
    expect(keys('unchecked')).toEqual(['core.never']);
    expect(uncheckedCount(groups, table)).toBe(1);
    expect(uncheckedCount(groups, null)).toBe(3);
  });

  it('drops a group with nothing left, and unchecked with no run at all keeps every widget', () => {
    expect(filterGroups(groups, '', 'failing', null)).toEqual([]);
    expect(filterGroups(groups, '', 'unchecked', null)[0]!.leaves).toHaveLength(3);
  });
});

describe('widgetStatus', () => {
  it('gives the verdict and the failure count the tree row words: not checked, pass, fails N', async () => {
    const { widgetStatus } = await import('./lab-model');
    const { SAMPLE_TABLE } = await import('./lab-test-bus');
    const table = SAMPLE_TABLE as unknown as FitTable;
    expect(widgetStatus(null, 'core.notes')).toEqual({ verdict: 'none', failures: 0 });
    const failing = table.widgets.find((row) => widgetStatus(table, row.widget).verdict === 'fail')!;
    expect(widgetStatus(table, failing.widget)).toEqual({ verdict: 'fail', failures: failing.failures });
    expect(widgetStatus(table, 'not.a.widget')).toEqual({ verdict: 'none', failures: 0 });
  });
});

describe('distinct widgets', () => {
  const leaves = [{ key: 'core.notes' }, { key: 'core.analytics:kpi' }, { key: 'core.analytics:bar' }, { key: 'core.analytics:line' }];

  it('counts the analytics presets as the one widget the gate records', () => {
    expect(widgetOf('core.analytics:kpi')).toBe('core.analytics');
    expect(widgetOf('core.notes')).toBe('core.notes');
    expect(widgetOf('draft:my-slug')).toBe('draft:my-slug');
    expect(distinctWidgets(leaves)).toBe(2);
  });

  it('gives a preset the verdict of its widget record, so no preset reads "not checked" beside a passed widget', () => {
    const table = { widgets: [{ widget: 'core.analytics', determined: true, failures: 0, cells: { 'home/m': { verdict: 'pass', red: false, draws: 1, reasons: [] } } }] } as unknown as FitTable;
    expect(widgetVerdict(table, 'core.analytics:kpi')).toBe('pass');
    expect(widgetVerdict(table, 'core.notes')).toBe('none');
  });

  it('gives a preset frame the verdict of its widget record too, so every verdict reader agrees', () => {
    const table = { widgets: [{ widget: 'core.analytics', determined: true, failures: 0, cells: { 'home/m': { verdict: 'pass', red: false, draws: 1, reasons: [] } } }] } as unknown as FitTable;
    expect(frameVerdict(table, 'core.analytics:kpi', 'home', 'm')).toEqual({ verdict: 'pass', reasons: [] });
    expect(frameVerdict(table, 'core.notes', 'home', 'm')).toBeNull();
  });
});
