/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const stub = vi.hoisted(() => ({ getPackSkills: vi.fn(), runPlan: vi.fn(), postHeld: vi.fn(), syncNow: vi.fn(), getDetail: vi.fn(), takeCopy: vi.fn() }));
vi.mock('./pack-skills-api', async (importActual) => ({ ...(await importActual<typeof import('./pack-skills-api')>()), ...stub }));

import PackSkillsTab from './PackSkillsTab.svelte';
import { data } from './pack-skills.svelte';

const peer = (label: string, state: string, conflicts: [string, string, string][] = []) => ({ label, state, applied_gen: 3, off_count: 0, conflicts });
const row = (name: string, state: string, synced: boolean, cells: Record<string, string>, reason = '') => ({ family: 'claude', name, synced, state, reason, digest: 'd1', cells });

const alphaView = () => ({
  role: 'alpha',
  alpha: { id: 'a', label: 'hostb' },
  gen: 3,
  problem: null,
  hold: null,
  choices: { mode: 'some', include: [['claude', 'sme']], exclude: [] },
  peers: { t: peer('hosta', 'in sync', [['claude', 'big', 'too large']]), m: peer('hostb', 'differs') },
  rows: [
    row('sme', 'synced', true, { t: 'in sync', m: 'syncing' }),
    row('new', 'synced', true, { t: 'missing', m: 'differs' }),
    row('lone', 'unsynced', false, { t: 'only here', m: 'same' }),
    row('big', 'synced', true, { t: 'conflict', m: 'offline' }),
    row('old', 'synced', true, { t: 'older carnivore', m: 'alpha is one way here' }),
    row('gone', 'held', false, { t: 'missing', m: 'missing' }, 'folder gone'),
  ],
});
const receiverView = () => ({
  role: 'receiver',
  read_only: true,
  alpha: { id: 'a', label: 'hostb' },
  applied_gen: 3,
  rows: [{ family: 'claude', name: 'sme', synced: true, state: 'in sync', digest: 'd1' }],
});
const preview = { skills: [], computers: [{ id: 't', label: 'hosta', state: 'ok', add: 1, replace: 0, same: 0, conflict: 0, skills: { 'claude/sme': 'will add' } }], total_bytes: 10, total_files: 2, choices: {}, plan_token: 'tok1' };

let app: ReturnType<typeof mount> | null = null;
const settle = async () => {
  for (let i = 0; i < 8; i++) await tick();
  flushSync();
};
const q = <T extends Element = HTMLElement>(sel: string) => document.querySelector<T>(sel);

async function open(view: unknown) {
  stub.getPackSkills.mockResolvedValue(view);
  data.status = 'loading';
  data.view = null;
  data.query = '';
  data.inventory = false;
  app = mount(PackSkillsTab, { target: document.body });
  await settle();
}

beforeEach(() => Object.values(stub).forEach((fn) => fn.mockReset()));
afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

test('every cell state is a word plus a shape mark', async () => {
  await open(alphaView());
  const cells = [...document.querySelectorAll<HTMLElement>('[data-pks-cell]')];
  const states = new Set(cells.map((c) => c.dataset.state));
  for (const s of ['in sync', 'syncing', 'missing', 'differs', 'only here', 'same', 'conflict', 'offline', 'older carnivore', 'alpha is one way here', 'missing on alpha']) {
    expect(states.has(s), s).toBe(true);
  }
  for (const c of cells) {
    expect(c.querySelector('.lsk-cell__mark')?.textContent?.length, c.dataset.state).toBeGreaterThan(0);
    expect(c.querySelector('.lsk-cell__word')?.textContent?.trim().length, c.dataset.state).toBeGreaterThan(0);
  }
  expect(q('[data-pks-cell="big|t"]')?.textContent).toContain('too large');
  expect(q('[data-pks-alpha]')?.textContent).toContain('hostb');
});

test('a computer that is not alpha is read only and says where to change it', async () => {
  await open(receiverView());
  expect(q('[data-pks-readonly]')?.textContent).toContain('change it on hostb');
  expect(q<HTMLButtonElement>('[data-pks-switch="sme"]')!.disabled).toBe(true);
  expect(q<HTMLButtonElement>('[data-pks-all]')!.disabled).toBe(true);
});

test('confirm exists only after the dry run answered and sends its plan token', async () => {
  await open(alphaView());
  let release!: (v: unknown) => void;
  stub.runPlan.mockImplementationOnce(() => new Promise((r) => (release = r)));
  q('[data-pks-switch="lone"]')!.click();
  await settle();
  expect(q('[data-pks-sheet]')).not.toBeNull();
  expect(q('[data-pks-confirm]')).toBeNull();
  release(preview);
  await settle();
  expect(q('[data-pks-confirm]')).not.toBeNull();
  expect(q('[data-pks-computer="t"]')?.textContent).toContain('will add');
  stub.runPlan.mockResolvedValueOnce({ ok: true });
  q('[data-pks-confirm]')!.click();
  await settle();
  const [call, dry, token] = stub.runPlan.mock.calls[1]!;
  expect(call).toMatchObject({ kind: 'skill', name: 'lone', synced: true, families: ['claude'] });
  expect([dry, token]).toEqual([false, 'tok1']);
  expect(stub.runPlan.mock.calls[0]![1]).toBe(true);
});

test('a missing on alpha row offers exactly its two actions', async () => {
  await open(alphaView());
  const acts = [...document.querySelectorAll<HTMLElement>('[data-pks-row="gone"] [data-pks-held]')].map((b) => b.dataset.pksHeld);
  expect(acts).toEqual(['stop_syncing', 'remove_everywhere']);
  expect(q('[data-pks-row="gone"] [data-pks-switch]')).toBeNull();
});

test('a receiver reason goes through the string catalog and an unknown one stays raw', async () => {
  const { reasonLabel, REASON_CODES } = await import('./pack-model');
  const table: Record<string, string> = { 'skills.pack.reason.no_harness': '{family} not on this computer', 'skills.pack.reason.version_revoked': 'version revoked' };
  const t = (key: string, p?: Record<string, unknown> | null) => (table[key] ?? key).replace('{family}', String(p?.family ?? ''));
  expect(reasonLabel('codex not on this computer', t)).toBe('codex not on this computer');
  expect(reasonLabel('version revoked', t)).toBe('version revoked');
  expect(reasonLabel('something an older computer said', t)).toBe('something an older computer said');
  expect(REASON_CODES).toContain('review_not_clean');
});

const withIcons = async (fn: () => Promise<void>) => {
  const w = window as unknown as { AgentFamilyIcon?: unknown };
  w.AgentFamilyIcon = { svg: (f: string) => `<svg data-fam="${f}"></svg>`, normalize: (f: string) => f, labelFor: (f: string) => `${f} agent` };
  try {
    await fn();
  } finally {
    delete w.AgentFamilyIcon;
  }
};
const codexRow = (name: string, state: string, synced: boolean, cells: Record<string, string>, reason = '') => ({ ...row(name, state, synced, cells, reason), family: 'codex' });

test('one row per skill name with both provider icons beside the name, the worst state in each cell', async () => {
  await withIcons(async () => {
    const v = alphaView();
    v.rows.push(codexRow('sme', 'synced', true, { t: 'differs', m: 'in sync' }));
    await open(v);
    expect(document.querySelectorAll('[data-pks-row="sme"]').length).toBe(1);
    const r = q('[data-pks-row="sme"]')!;
    const marks = [...r.querySelectorAll<HTMLElement>('[data-pks-family]')];
    expect(marks.map((m) => m.dataset.pksFamily)).toEqual(['claude', 'codex']);
    expect(marks[0]!.querySelector('svg[data-fam="claude"]')).not.toBeNull();
    expect(marks[1]!.querySelector('svg[data-fam="codex"]')).not.toBeNull();
    expect(r.querySelector('[data-pks-detail-open]')!.previousElementSibling).toBe(marks[1]);
    expect(r.querySelector('.lsk-col__sub')).toBeNull();
    expect(q('[data-pks-cell="sme|t"]')!.dataset.state).toBe('differs');
    expect(q('[data-pks-cell="sme|m"]')!.dataset.state).toBe('syncing');
    expect(q('[data-pks-switch="sme"]')!.classList.contains('pks-on')).toBe(true);
    expect(q('[data-pks-switch="lone"]')!.classList.contains('pks-on')).toBe(false);
  });
});

test('the switch of a two-family skill asks one plan for both families; a family that cannot sync shows a held mark', async () => {
  await withIcons(async () => {
    const v = alphaView();
    v.rows.push(codexRow('sme', 'synced', true, { t: 'in sync', m: 'in sync' }), codexRow('big', 'held', false, { t: 'missing', m: 'missing' }, 'too large'));
    await open(v);
    stub.runPlan.mockResolvedValue(preview);
    q('[data-pks-switch="sme"]')!.click();
    await settle();
    expect(stub.runPlan.mock.calls[0]![0]).toMatchObject({ kind: 'skill', name: 'sme', synced: false, families: ['claude', 'codex'] });
    expect(document.querySelectorAll('[data-pks-row="big"]').length).toBe(1);
    expect(q('[data-pks-row="big"] [data-pks-switch="big"]')).not.toBeNull();
    expect(q('[data-pks-row="big"] [data-pks-held-mark="codex"]')!.textContent).toContain('too large');
  });
});

test('the header row is sticky, on its own class, and the column labels share one label style', async () => {
  await open(alphaView());
  const head = q('thead.pks-head')!;
  expect(head).not.toBeNull();
  expect(q('[data-pks-matrix]')!.classList.contains('lsk-scroll--pack')).toBe(true);
  const css = (await import('node:fs')).readFileSync('src/lib/skills-hub/local/local-skills.css', 'utf8');
  const rule = css.slice(css.indexOf('.pledger .lsk-table .pks-head th {'), css.indexOf('}', css.indexOf('.pledger .lsk-table .pks-head th {')));
  expect(rule).toContain('position: sticky');
  expect(rule).toContain('top: 0');
  expect(rule).toContain('--oc-ground-titlerow');
  expect(rule).toContain('text-transform: uppercase');
  expect(rule).not.toMatch(/#[0-9a-f]{3,6}\b/i);
  expect([...head.querySelectorAll('th')].length).toBe(5);
});

test('a one-skill sheet says how many other skills were left out of the preview, in one quiet line', async () => {
  await open(alphaView());
  stub.runPlan.mockResolvedValueOnce({ ...preview, others: 3 });
  q('[data-pks-switch="lone"]')!.click();
  await settle();
  expect(q('[data-pks-others]')!.textContent).toMatch(/3/);
  expect(q('[data-pks-sheet]')!.textContent).not.toContain('ashhaven');
});

test('a skill with one held family and one syncable family keeps stop syncing and remove everywhere', async () => {
  await withIcons(async () => {
    const v = alphaView();
    v.rows.push(codexRow('sme', 'synced', true, { t: 'in sync', m: 'in sync' }), codexRow('big', 'held', false, { t: 'missing', m: 'missing' }, 'too large'));
    await open(v);
    const acts = [...document.querySelectorAll<HTMLElement>('[data-pks-row="big"] [data-pks-held]')].map((b) => b.dataset.pksHeld);
    expect(acts).toEqual(['stop_syncing', 'remove_everywhere']);
    expect(q('[data-pks-row="big"] [data-pks-switch="big"]')).not.toBeNull();
    expect(q('[data-pks-row="sme"] [data-pks-held]')).toBeNull();
  });
});

async function cascaded(el: Element, prop: string, inherited: boolean): Promise<string | null> {
  const { parse, walk, generate } = await import('css-tree');
  const css = (await import('node:fs')).readFileSync('src/lib/skills-hub/local/local-skills.css', 'utf8');
  let best: { spec: number[]; order: number; value: string } | null = null;
  let order = 0;
  walk(parse(css), {
    visit: 'Rule',
    enter(rule: any) {
      order++;
      rule.prelude.children.forEach((sel: any) => {
        const text = generate(sel);
        let hit = false;
        try { hit = el.matches(text); } catch { return; }
        if (!hit) return;
        const spec = [0, 0, 0];
        walk(sel, (n: any) => {
          if (n.type === 'IdSelector') spec[0]!++;
          else if (n.type === 'ClassSelector' || n.type === 'AttributeSelector' || n.type === 'PseudoClassSelector') spec[1]!++;
          else if (n.type === 'TypeSelector' && n.name !== '*') spec[2]!++;
        });
        rule.block.children.forEach((d: any) => {
          if (d.type !== 'Declaration' || d.property !== prop) return;
          const wins = !best || spec[0]! > best.spec[0]! || (spec[0] === best.spec[0] && (spec[1]! > best.spec[1]! || (spec[1] === best.spec[1] && (spec[2]! > best.spec[2]! || (spec[2] === best.spec[2] && order >= best.order)))));
          if (wins) best = { spec, order, value: generate(d.value) };
        });
      });
    },
  });
  if (best) return (best as { value: string }).value;
  return inherited && el.parentElement ? cascaded(el.parentElement, prop, inherited) : null;
}

test('SKILL, GLOBAL and a computer label wear one label style, and the header keeps its hairline', async () => {
  await open(alphaView());
  document.body.classList.add('pledger');
  const ths = [...document.querySelectorAll('thead.pks-head th')];
  const label = q('thead.pks-head .lsk-col__label')!;
  const targets = [ths[0]!, ths[1]!, label];
  for (const prop of ['color', 'letter-spacing', 'font-size', 'text-transform', 'font-weight']) {
    const values = await Promise.all(targets.map((el) => cascaded(el, prop, true)));
    expect(new Set(values).size, `${prop}: ${values.join(' | ')}`).toBe(1);
  }
  expect(await cascaded(targets[0]!, 'color', true)).toBe('var(--oc-text-muted)');
  expect(await cascaded(targets[0]!, 'letter-spacing', true)).toContain('--oc-tracking-label');
  expect(await cascaded(ths[0]!, 'box-shadow', false)).toContain('--oc-line-rule');
  expect(await cascaded(ths[1]!, 'box-shadow', false)).toContain('--oc-line-rule');
});

const takePreview = { family: 'claude', name: 'new', digest: 'd9', files: 2, bytes: 40, scripts: ['scripts/run.sh'], here: 'differs', from: 'hostb', plan_token: 'tk9' };

test('take it shows on another computers differing cell only, and its sheet confirms after the dry run with its token', async () => {
  const view = alphaView();
  view.rows.push({ ...row('cat', 'synced', true, { t: 'differs', m: 'in sync' }), warez: { item: 'a/b', version: '1.0.0' } } as never);
  await open(view);
  expect(q('[data-pks-take="new|m"]')).not.toBeNull();
  expect(q('[data-pks-take="new|t"]')).toBeNull();
  expect(q('[data-pks-take="sme|t"]')).toBeNull();
  expect(q('[data-pks-take="new|self"]')).toBeNull();
  expect(q('[data-pks-take="cat|t"]')).toBeNull();
  let release!: (v: unknown) => void;
  stub.takeCopy.mockImplementationOnce(() => new Promise((r) => (release = r)));
  q('[data-pks-take="new|m"]')!.click();
  await settle();
  expect(q('[data-pks-take-sheet]')).not.toBeNull();
  expect(q('[data-pks-take-confirm]')).toBeNull();
  release(takePreview);
  await settle();
  expect(q('[data-pks-take-here="differs"]')?.textContent).toContain('replaced');
  expect(q('[data-pks-take-plan]')?.textContent).toContain('scripts/run.sh');
  stub.takeCopy.mockResolvedValueOnce({ ok: true, placed: 2, conflicts: [] });
  q('[data-pks-take-confirm]')!.click();
  await settle();
  expect(stub.takeCopy.mock.calls[0]).toEqual(['m', 'claude', 'new', true]);
  expect(stub.takeCopy.mock.calls[1]).toEqual(['m', 'claude', 'new', false, 'tk9']);
  expect(q('[data-pks-take-sheet]')).toBeNull();
});

test('a refusal is said in words and leaves no confirm; a receiver and the inventory switch', async () => {
  await open(alphaView());
  stub.takeCopy.mockRejectedValueOnce(Object.assign(new Error('x'), { payload: { detail: { code: 'needs_update' } } }));
  q('[data-pks-take="new|m"]')!.click();
  await settle();
  expect(q('[data-pks-notice]')?.textContent).toContain('older carnivore');
  expect(q('[data-pks-take-confirm]')).toBeNull();
  q('[data-pks-cancel]')!.click();
  await settle();
  q('[data-pks-inventory]')!.click();
  await settle();
  expect(stub.getPackSkills).toHaveBeenLastCalledWith(true);
  if (app) unmount(app);
  document.body.innerHTML = '';
  await open(receiverView());
  expect(q('[data-pks-take]')).toBeNull();
  expect(q<HTMLButtonElement>('[data-pks-inventory]')!.disabled).toBe(true);
});
