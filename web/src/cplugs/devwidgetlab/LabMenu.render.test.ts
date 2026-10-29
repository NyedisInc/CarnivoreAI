/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const api = vi.hoisted(() => ({ labStatus: vi.fn(), runCapture: vi.fn(), fitTableState: vi.fn(), startMatrix: vi.fn() }));
vi.mock('./lab-api', async (importOriginal) => ({ ...(await importOriginal<typeof import('./lab-api')>()), ...api }));

import LabMenu from './LabMenu.svelte';
import LabViewer from './LabViewer.svelte';
import { labWidgets } from '../sdk/widget-lab';
import { distinctWidgets } from './lab-model';
import { setLocale } from '../../lib/i18n/index.svelte';
import { LAB_CHANNEL, PREVIEW_WIDTHS_SHOWN, SELECTION_KEY } from './lab-selection';
import { channelNames, installLabBus, SAMPLE_TABLE } from './lab-test-bus';
import { pickOption } from './lab-test-dropdown';
import { readLabCss } from '../../lib/test-support/lab-css';

setLocale('en');

const mounted: ReturnType<typeof mount>[] = [];

async function settle(): Promise<void> {
  for (let i = 0; i < 8; i += 1) {
    await Promise.resolve();
    await tick();
    flushSync();
  }
}

async function openBoth(): Promise<{ menu: HTMLElement; view: HTMLElement }> {
  const menu = document.body.appendChild(document.createElement('div'));
  const view = document.body.appendChild(document.createElement('div'));
  mounted.push(mount(LabMenu, { target: menu }));
  mounted.push(mount(LabViewer, { target: view }));
  await settle();
  return { menu, view };
}

const frames = (root: HTMLElement) => [...root.querySelectorAll<HTMLIFrameElement>('iframe.dwl-frame')];
const param = (frame: HTMLIFrameElement, name: string) => new URL(frame.src, 'http://x.test').searchParams.get(name);
const button = (root: HTMLElement, text: string) => [...root.querySelectorAll<HTMLButtonElement>('button')].find((b) => b.textContent?.trim() === text)!;
const captureKey = (root: HTMLElement) => root.querySelector<HTMLButtonElement>('.dwl-foot-key')!;
const leaf = (root: HTMLElement, key: string) => root.querySelector<HTMLButtonElement>(`.dwl-leaf[data-key="${key}"]`)!;

beforeEach(() => {
  installLabBus();
  api.labStatus.mockResolvedValue({ available: true, reason: '', captures_dir: '/x/captures' });
  api.runCapture.mockReset();
  api.startMatrix.mockReset();
  api.fitTableState.mockReset();
  api.fitTableState.mockResolvedValue({ available: true, reason: '', running: false, started: null, exit: null, table: null });
});

afterEach(() => {
  while (mounted.length) unmount(mounted.pop()!);
  document.body.innerHTML = '';
});

describe('the menu', () => {
  it('opens in the order things are used and opens no browser page itself', async () => {
    const { menu } = await openBoth();
    const kids = [...menu.querySelector('.dwl-menu')!.children];
    expect(kids.map((node) => node.className)).toEqual(['dwl-scroll', 'dwl-links']);
    const scroll = menu.querySelector('.dwl-scroll')!;
    const order = ['.dwl-filter', '.dwl-all', '.dwl-tree .dwl-group', '.dwl-rows', '.dwl-sec[data-open="no"]', '.dwl-foot', '.dwl-checks'].map((sel) => scroll.querySelector(sel));
    expect(order.every((node) => node !== null)).toBe(true);
    const all = [...scroll.querySelectorAll('*')];
    const at = order.map((node) => all.indexOf(node as Element));
    expect([...at].sort((a, b) => a - b)).toEqual(at);
    expect(menu.querySelectorAll('.dwl-sec[data-open="yes"]').length).toBe(3);
    expect(menu.querySelectorAll('.dwl-sec[data-open="no"]').length).toBe(1);
  });

  it('has no status row or "view only" area, and its sections run preview, scenario, capture, checks (checks last)', async () => {
    const { menu } = await openBoth();
    expect(menu.querySelector('.dwl-toolbar')).toBeNull();
    expect(menu.querySelector('.dwl-status')).toBeNull();
    expect(menu.textContent).not.toContain('view only');
    expect([...menu.querySelectorAll('.dwl-sec-head .dwl-sec-label')].map((one) => one.textContent)).toEqual(['preview', 'json scenario', 'capture', 'checks']);
  });

  it('picks each drawer as its own "show in" row (all on to start), one band each, and the viewer follows through the channel', async () => {
    const { menu, view } = await openBoth();
    const checked = (id: string) => menu.querySelector(`[data-choice="show-in"] [data-choice-option="${id}"]`)!.getAttribute('aria-selected');
    const drawn = () => [...view.querySelectorAll<HTMLElement>('.dwl-host[data-host="drawer"] .dwl-chrome')].map((one) => one.dataset['dock']);
    expect(drawn()).toEqual(['left', 'bottom', 'right']);
    pickOption(menu, 'show-in', 'right');
    await settle();
    expect(drawn()).toEqual(['left', 'bottom']);
    expect(checked('right')).toBe('false');
    pickOption(menu, 'show-in', 'left');
    await settle();
    expect(drawn()).toEqual(['bottom']);
    pickOption(menu, 'show-in', 'bottom');
    await settle();
    expect(drawn()).toEqual([]);
    expect(view.querySelectorAll('.dwl-host[data-host="drawer"]').length).toBe(0);
    pickOption(menu, 'show-in', 'left');
    await settle();
    expect(drawn()).toEqual(['left']);
    expect(checked('left')).toBe('true');
  });

  it('is a column: the style guide link is pinned and everything above it scrolls as ONE region', async () => {
    const { menu } = await openBoth();
    const scroll = menu.querySelector('.dwl-scroll')!;
    expect(scroll.contains(menu.querySelector('.dwl-tree'))).toBe(true);
    expect(scroll.contains(menu.querySelector('.dwl-sec[data-open="yes"] .dwl-rows'))).toBe(true);
    const labCss = readLabCss();
    const rule = (name: string) => new RegExp(`\\.${name} \\{([^}]*)\\}`).exec(labCss)![1]!;
    expect(rule('dwl-menu')).toMatch(/flex-direction: column/);
    expect(rule('dwl-scroll')).toMatch(/flex: 1 1 auto/);
    expect(rule('dwl-scroll')).toMatch(/overflow-y: auto/);
    expect(rule('dwl-tree')).not.toMatch(/overflow/);
    expect(rule('dwl-links')).toMatch(/flex: none/);
  });

  it('shows each folded section\'s current value in its header', async () => {
    const { menu } = await openBoth();
    const heads = [...menu.querySelectorAll('.dwl-sec-head')].map((head) => head.querySelector('.dwl-sec-value')!.textContent);
    expect(heads[0]).toBe('6 places / normal');
    expect(heads[1]).toBe('none');
    expect(heads[2]).toBe('6 frames');
    expect(heads[3]).toBe('not run');
  });

  it('a pick and a band size flip change what the viewer draws, through the channel', async () => {
    const { menu, view } = await openBoth();
    const first = labWidgets().find((w) => w.key !== 'core.notes' && w.hosts.every((h) => h.supported))!;
    expect(frames(view).length).toBe(6);
    view.querySelector<HTMLButtonElement>('.dwl-host[data-host="home"] .dwl-size-key[data-size="l"]')!.click();
    await settle();
    expect(frames(view).length).toBe(6);
    expect(frames(view).map((f) => param(f, 'size')).sort()).toEqual(['l', 'm', 'm', 'm', 'm', 'm']);
    expect(captureKey(menu).textContent).toContain('capture 6 frames');
    pickOption(menu, 'fixture', 'stress');
    await settle();
    expect(frames(view).every((f) => param(f, 'fixture') === 'stress')).toBe(true);
    leaf(menu, first.key).click();
    await settle();
    expect(frames(view).every((f) => param(f, 'widget') === first.key)).toBe(true);
  });

  it('steps the theme with its keys and the viewer follows', async () => {
    const { menu, view } = await openBoth();
    menu.querySelector<HTMLButtonElement>('[aria-label="next theme"]')!.click();
    await settle();
    expect(frames(view).every((f) => param(f, 'theme') === 'blade_runner')).toBe(true);
  });

  it('a fit-cell press on the viewer picks the widget in the menu and focuses the frame', async () => {
    api.fitTableState.mockResolvedValue({ available: true, reason: '', running: false, started: null, exit: 1, table: SAMPLE_TABLE });
    const { menu, view } = await openBoth();
    menu.querySelector<HTMLButtonElement>('[data-all-fit]')!.click();
    await settle();
    expect(view.querySelector('.dwl-fit')).not.toBeNull();
    expect(menu.querySelector('.dwl-sec-value')!.textContent).toBeTruthy();
    (view.querySelector('.dwl-fit-cell[data-state="red"]') as HTMLButtonElement).click();
    await settle();
    expect(leaf(menu, 'core.notes').getAttribute('aria-current')).toBe('true');
    expect(view.querySelector('.dwl-preview[data-focused="yes"]')).not.toBeNull();
    expect(button(menu, 'capture 1 frame')).toBeTruthy();
  });

  it('the find field narrows the tree and the results select keeps only widgets the last run failed', async () => {
    api.fitTableState.mockResolvedValue({ available: true, reason: '', running: false, started: null, exit: 1, table: SAMPLE_TABLE });
    const { menu } = await openBoth();
    const select = menu.querySelector<HTMLSelectElement>('.dwl-result')!;
    const failing = [...select.options].find((one) => one.value === 'failing')!;
    expect(failing.textContent).toBe('failing (2)');
    expect(failing.disabled).toBe(false);
    select.value = 'failing';
    select.dispatchEvent(new Event('change', { bubbles: true }));
    await settle();
    expect([...menu.querySelectorAll('.dwl-leaf[data-key]')].map((one) => (one as HTMLElement).dataset['key'])).toEqual(['core.notes']);
    select.value = 'all';
    select.dispatchEvent(new Event('change', { bubbles: true }));
    const field = menu.querySelector('input[type="search"]') as HTMLInputElement;
    field.value = 'zzzz-nothing';
    field.dispatchEvent(new Event('input', { bubbles: true }));
    await settle();
    expect(menu.querySelector('.dwl-tree-empty')!.textContent).toContain('no widget matches');
  });

  it('turns the failing result off with no run yet, and keeps unchecked on', async () => {
    const { menu } = await openBoth();
    const options = [...menu.querySelectorAll<HTMLOptionElement>('.dwl-result option')];
    expect(options.map((one) => one.textContent)).toEqual(['all results', 'failing (0)', `unchecked (${distinctWidgets(labWidgets())})`]);
    expect(options[1]!.disabled).toBe(true);
    expect(options[2]!.disabled).toBe(false);
  });

  it('says each widget row\'s status as a dot and a word: not checked, pass, fails N', async () => {
    api.fitTableState.mockResolvedValue({ available: true, reason: '', running: false, started: null, exit: 1, table: SAMPLE_TABLE });
    const { menu } = await openBoth();
    expect(leaf(menu, 'core.notes').querySelector('.dwl-dot')!.getAttribute('data-verdict')).toBe('fail');
    expect(leaf(menu, 'core.notes').querySelector('.dwl-verdict')!.textContent).toMatch(/^fails \d+$|^fail$/);
    const unjudged = [...menu.querySelectorAll<HTMLElement>('.dwl-leaf[data-key]')].find((one) => one.querySelector('.dwl-verdict')!.getAttribute('data-verdict') === 'none')!;
    expect(unjudged.querySelector('.dwl-verdict')!.textContent).toBe('not checked');
  });
});

describe('the CHECKS block', () => {
  const idle = { available: true, reason: '', running: false, started: null, exit: null, table: null };
  const select = (menu: HTMLElement) => menu.querySelector<HTMLSelectElement>('#dwl-scope')!;
  const runKey = (menu: HTMLElement) => menu.querySelector<HTMLButtonElement>('[data-run-checks]')!;

  it('is open by default with a scope select, run checks, results, a summary and a note of what checks cover', async () => {
    const { menu } = await openBoth();
    const body = menu.querySelector('.dwl-checks')!;
    expect(body).not.toBeNull();
    expect([...select(menu).options].map((one) => one.textContent)).toEqual([`all ${distinctWidgets(labWidgets())} widgets`, 'selected widget']);
    expect(menu.querySelector('[data-summary]')!.textContent).toBe('not checked yet.');
    expect(body.textContent).toContain('never replace the approved reference images');
    expect(body.textContent).toContain('also write catalog images');
  });

  it('runs every widget by default and passes the catalog tick along', async () => {
    api.startMatrix.mockResolvedValue({ state: { ...idle, running: true }, refusal: '' });
    const { menu } = await openBoth();
    [...menu.querySelectorAll<HTMLButtonElement>('.dwl-checks .dwl-choice')].find((one) => one.textContent?.includes('catalog'))!.click();
    await settle();
    runKey(menu).click();
    await settle();
    expect(api.startMatrix).toHaveBeenCalledWith(true, null);
  });

  it('runs only the selected widget through the route\'s only parameter', async () => {
    api.startMatrix.mockResolvedValue({ state: { ...idle, running: true }, refusal: '' });
    const { menu } = await openBoth();
    select(menu).value = 'selected';
    select(menu).dispatchEvent(new Event('change', { bubbles: true }));
    await settle();
    runKey(menu).click();
    await settle();
    expect(api.startMatrix).toHaveBeenCalledWith(false, 'core.notes');
  });

  it('turns "selected widget" off while the fit table is on show, and runs everything then', async () => {
    api.startMatrix.mockResolvedValue({ state: { ...idle, running: true }, refusal: '' });
    const { menu } = await openBoth();
    menu.querySelector<HTMLButtonElement>('[data-all-fit]')!.click();
    await settle();
    expect(select(menu).options[1]!.disabled).toBe(true);
    runKey(menu).click();
    await settle();
    expect(api.startMatrix).toHaveBeenCalledWith(false, null);
  });

  it('the results key opens the fit table, and the header and summary say the last run', async () => {
    api.fitTableState.mockResolvedValue({ available: true, reason: '', running: false, started: null, exit: 1, table: SAMPLE_TABLE });
    const { menu, view } = await openBoth();
    const { pass, fail } = SAMPLE_TABLE.counts;
    expect([...menu.querySelectorAll('.dwl-sec-value')].at(-1)!.textContent).toBe(`last run ${pass} pass, ${fail} fail`);
    expect(menu.querySelector('[data-summary]')!.getAttribute('data-tone')).toBe(fail > 0 ? 'bad' : 'ok');
    menu.querySelector<HTMLButtonElement>('[data-show-results]')!.click();
    await settle();
    expect(view.querySelector('.dwl-fit')).not.toBeNull();
  });

  it('says a refusal once and keeps the run key off while a run is going', async () => {
    api.startMatrix.mockResolvedValue({ state: null, refusal: 'a matrix run is already going' });
    const { menu } = await openBoth();
    runKey(menu).click();
    await settle();
    expect(menu.querySelector('.dwl-checks')!.textContent).toContain('a matrix run is already going');
    while (mounted.length) unmount(mounted.pop()!);
    document.body.innerHTML = '';
    api.fitTableState.mockResolvedValue({ ...idle, running: true });
    const busy = await openBoth();
    expect(runKey(busy.menu).disabled).toBe(true);
  });
});

describe('the PREVIEW block', () => {
  const rowsOf = (menu: HTMLElement, key: string) => [...menu.querySelectorAll<HTMLElement>(`[data-choice="${key}"] [data-choice-option]`)];

  it('offers "show in" as a dropdown of checks, keeps the list open while picking, and keeps at least one on', async () => {
    const { menu } = await openBoth();
    const host = menu.querySelector<HTMLElement>('[data-choice="show-in"]')!;
    expect(host.closest('.dwl-row')!.querySelector('.dwl-label')!.textContent).toBe('show in');
    pickOption(menu, 'show-in', 'popout');
    await settle();
    expect(host.querySelector('[data-choice-list]')!.getAttribute('aria-multiselectable')).toBe('true');
    expect(rowsOf(menu, 'show-in').map((one) => one.getAttribute('data-choice-option'))).toEqual(['home', 'terminal', 'left', 'bottom', 'right', 'popout']);
    expect(rowsOf(menu, 'show-in').map((one) => one.textContent?.trim())).toEqual(['home grid', 'terminal grid', 'left drawer', 'bottom drawer', 'right drawer', 'pop-out window']);
    expect(menu.querySelector('.dwl-field[aria-label="drawer"]')).toBeNull();
    const on = () => rowsOf(menu, 'show-in').filter((one) => one.getAttribute('aria-selected') === 'true');
    expect(on().length).toBe(5);
    for (const id of ['home', 'terminal', 'left', 'bottom']) {
      pickOption(menu, 'show-in', id);
      await settle();
    }
    expect(on().map((one) => one.getAttribute('data-choice-option'))).toEqual(['right']);
    pickOption(menu, 'show-in', 'right');
    await settle();
    expect(on().length).toBe(1);
  });

  it('keeps the confirm-edge rule for a chosen option in the lab stylesheet (tokens only)', () => {
    const css = readLabCss();
    const on = css.slice(css.indexOf(".dwl-choice[data-on='yes'] {"), css.indexOf('}', css.indexOf(".dwl-choice[data-on='yes'] {")));
    expect(on).toContain('border-color: var(--oc-green)');
    expect(on).toContain('background: color-mix(');
    expect(on).not.toMatch(/#[0-9a-f]{3,8}\b|rgb\(/i);
  });

  it('no longer shows the width controls (each band\'s header switches its own size), and the header reads show in / sample data', async () => {
    const { menu } = await openBoth();
    expect(menu.querySelector('.dwl-field[aria-label="size"]')).toBeNull();
    expect(menu.querySelector('.dwl-more-key')).toBeNull();
    expect(menu.textContent).not.toMatch(/select one or more\s*S \//);
    expect([...menu.querySelectorAll('.dwl-choice')].some((one) => /^[SML] \/ \d+/.test(one.textContent?.trim() ?? ''))).toBe(false);
    expect(menu.querySelector('.dwl-rows')!.closest('.dwl-sec')!.querySelector('.dwl-sec-value')!.textContent).toBe('6 places / normal');
    expect(PREVIEW_WIDTHS_SHOWN).toBe(false);
  });

  it('has sample data as a one-choice dropdown (normal, empty, stress), then the theme below it, and no show-menu or show-bars checks', async () => {
    const { menu } = await openBoth();
    menu.querySelector<HTMLElement>('[data-choice="fixture"] [data-choice-trigger]')!.click();
    await settle();
    expect(rowsOf(menu, 'fixture').map((one) => one.textContent?.trim())).toEqual(['normal', 'empty', 'stress']);
    expect(rowsOf(menu, 'fixture')[0]!.getAttribute('aria-selected')).toBe('true');
    expect(menu.querySelector('[data-choice="fixture"] [data-choice-list]')!.getAttribute('aria-multiselectable')).toBeNull();
    const labels = [...menu.querySelectorAll('.dwl-rows .dwl-label')].map((one) => one.textContent);
    expect(labels).toEqual(['show in', 'sample data', 'theme']);
    expect(menu.querySelector('.dwl-rows')!.textContent).not.toContain('show widget menu');
    expect(menu.querySelector('.dwl-rows')!.textContent).not.toContain('show menu bars');
  });
});

describe('capture', () => {
  it('is one button, in its own section, that captures every frame on show, one at a time, with the menu state taken from the selection', async () => {
    api.runCapture.mockResolvedValueOnce({ ok: true, determined: true, failures: [] }).mockResolvedValue({ ok: false, determined: true, failures: ['fit finding overlap: x'] });
    const { menu, view } = await openBoth();
    const key = captureKey(menu);
    key.click();
    await settle();
    expect(api.runCapture).toHaveBeenCalledTimes(6);
    expect(api.runCapture.mock.calls[0]![0]).toEqual({ widget: 'core.notes', host: 'home', size: 'm', theme: 'carnivore', fixture: 'data', state: 'normal' });
    expect(menu.querySelector('.dwl-foot')!.textContent).toContain('captured 1, 5 failed');
    expect(view.querySelector('.dwl-results')!.hasAttribute('open')).toBe(true);
    expect(view.querySelector('.dwl-result[data-ok="no"]')!.textContent).toContain('fit finding overlap: x');
  });

  it('has no capture key on a frame, and "capture with menu" is gone', async () => {
    const { menu, view } = await openBoth();
    expect(view.textContent).not.toContain('capture with menu');
    expect(menu.textContent).not.toContain('capture with menu');
    expect(view.querySelectorAll('.dwl-host-actions').length).toBe(0);
  });

  it('turns the key off and says why once when a capture cannot run here, with no "view only" anywhere', async () => {
    api.labStatus.mockResolvedValue({ available: false, reason: 'no_checkout', captures_dir: '' });
    const { menu } = await openBoth();
    expect(captureKey(menu).disabled).toBe(true);
    expect(menu.querySelector('.dwl-foot')!.textContent).toContain('source code of the app');
    expect(menu.textContent).not.toContain('view only');
    expect(menu.textContent!.split('source code of the app').length - 1).toBe(1);
  });

  it('keeps the CHECKS fold the person chose, and starts it open', async () => {
    const first = await openBoth();
    expect(first.menu.querySelector('.dwl-checks')).not.toBeNull();
    while (mounted.length) unmount(mounted.pop()!);
    document.body.innerHTML = '';
    localStorage.setItem(SELECTION_KEY, JSON.stringify({ folds: { checks: false } }));
    const { menu } = await openBoth();
    expect([...menu.querySelectorAll('.dwl-sec-head')].at(-1)!.getAttribute('aria-expanded')).toBe('false');
    expect(menu.querySelector('.dwl-checks')).toBeNull();
  });

  it('counts distinct widgets everywhere: the card, the top-level fold, the scope and each group agree', async () => {
    const { menu } = await openBoth();
    const total = distinctWidgets(labWidgets());
    expect(total).toBeLessThan(labWidgets().length);
    expect(menu.querySelector('.dwl-all .dwl-group-count')!.textContent).toBe(String(total));
    const groups = [...menu.querySelectorAll('.dwl-tree .dwl-group--nested .dwl-group-count')].reduce((sum, node) => sum + Number.parseInt(node.textContent!, 10), 0);
    expect(groups).toBe(total);
  });
});

describe('the lab keeps to its own storage', () => {
  it('writes no browser key and opens no channel outside the devwidgetlab names, whatever the menu and viewer do', async () => {
    api.fitTableState.mockResolvedValue({ available: true, reason: '', running: false, started: null, exit: 1, table: SAMPLE_TABLE });
    api.runCapture.mockResolvedValue({ ok: true, determined: true, failures: [] });
    const { menu, view } = await openBoth();
    view.querySelector<HTMLButtonElement>('.dwl-host[data-host="home"] .dwl-size-key[data-size="l"]')!.click();
    await settle();
    captureKey(menu).click();
    menu.querySelector<HTMLButtonElement>('.dwl-sec-head')!.click();
    view.querySelector<HTMLElement>('.dwl-cap-key')!.click();
    await settle();
    const keys = Object.keys(localStorage);
    expect(keys.length).toBeGreaterThan(0);
    expect(keys.every((key) => key.startsWith('devwidgetlab.'))).toBe(true);
    expect(keys).toContain(SELECTION_KEY);
    expect(sessionStorage.length).toBe(0);
    expect([...channelNames]).toEqual([LAB_CHANNEL]);
    expect(LAB_CHANNEL.startsWith('devwidgetlab.')).toBe(true);
    expect(Object.keys(api).sort()).toEqual(['fitTableState', 'labStatus', 'runCapture', 'startMatrix']);
  });
});

describe('the widget tree', () => {
  const proto = HTMLElement.prototype as unknown as { showPopover?: () => void; hidePopover?: () => void };
  proto.showPopover ??= function () {};
  proto.hidePopover ??= function () {};
  const groupHead = (menu: HTMLElement, id: string) => menu.querySelector<HTMLButtonElement>(`.dwl-group[data-group="${id}"]`)!;

  it('is a collapsible tree by the drawer\'s categories, each group a fold with its count, and the fit table is the entry above them', async () => {
    const { menu } = await openBoth();
    const tree = menu.querySelector('.dwl-tree')!;
    expect(tree.firstElementChild!.hasAttribute('data-all-fit')).toBe(true);
    expect(tree.firstElementChild!.textContent).toContain('all widgets');
    expect(tree.firstElementChild!.textContent).toContain('full-page review');
    const notes = labWidgets().find((w) => w.key === 'core.notes')!;
    const count = labWidgets().filter((w) => w.category === notes.category).length;
    const head = groupHead(menu, notes.category);
    expect(head.querySelector('.dwl-group-count')!.textContent).toBe(String(count));
    expect(head.getAttribute('aria-expanded')).toBe('true');
    expect(head.querySelector('.session-sidebar-group__chevron')).not.toBeNull();
    const other = [...menu.querySelectorAll<HTMLButtonElement>('.dwl-tree .dwl-group--nested')].find((one) => one !== head)!;
    expect(other.getAttribute('aria-expanded')).toBe('false');
  });

  const rootHead = (menu: HTMLElement) => menu.querySelector<HTMLButtonElement>('.dwl-group--root')!;
  const nested = (menu: HTMLElement) => [...menu.querySelectorAll<HTMLButtonElement>('.dwl-group--nested')];
  const click = (node: HTMLElement, shiftKey = false) => node.dispatchEvent(new MouseEvent('click', { bubbles: true, shiftKey }));

  it('has one top-level "widgets" fold above every group: it hides and shows all of them at once, and keeps each group\'s own fold underneath', async () => {
    const { menu } = await openBoth();
    expect(rootHead(menu).textContent).toContain('widgets');
    expect(rootHead(menu).getAttribute('aria-expanded')).toBe('true');
    const before = nested(menu).map((one) => one.getAttribute('aria-expanded'));
    expect(nested(menu).length).toBeGreaterThan(1);
    click(rootHead(menu));
    await settle();
    expect(rootHead(menu).getAttribute('aria-expanded')).toBe('false');
    expect(nested(menu)).toHaveLength(0);
    expect(menu.querySelectorAll('.dwl-leaf').length).toBe(0);
    click(rootHead(menu));
    await settle();
    expect(nested(menu).map((one) => one.getAttribute('aria-expanded'))).toEqual(before);
  });

  it('Shift+click on any chevron folds or unfolds EVERY fold; a plain click changes only its own', async () => {
    const { menu } = await openBoth();
    const open = () => nested(menu).map((one) => one.getAttribute('aria-expanded'));
    click(nested(menu)[1]!);
    await settle();
    expect(open().filter((one) => one === 'true').length).toBeGreaterThan(1);
    click(nested(menu).find((one) => one.getAttribute('aria-expanded') === 'true')!, true);
    await settle();
    expect(open().every((one) => one === 'false')).toBe(true);
    click(rootHead(menu), true);
    await settle();
    expect(rootHead(menu).getAttribute('aria-expanded')).toBe('true');
    expect(open().every((one) => one === 'true')).toBe(true);
    click(nested(menu)[2]!, true);
    await settle();
    expect(open().every((one) => one === 'false')).toBe(true);
    expect(JSON.parse(localStorage.getItem('devwidgetlab.tree.folds')!)['*widgets']).toBe(false);
  });

  it('opens a read-only row menu on a right-click (browser menu suppressed): show in viewer and copy key, nothing that writes', async () => {
    const { menu } = await openBoth();
    const row = menu.querySelector<HTMLButtonElement>('.dwl-leaf[data-key="core.notes"]')!;
    const event = new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 40, clientY: 60 });
    row.dispatchEvent(event);
    await settle();
    expect(event.defaultPrevented).toBe(true);
    const items = [...document.querySelectorAll<HTMLElement>('[role="menuitem"]')].map((one) => one.textContent ?? '');
    expect(items).toHaveLength(2);
    expect(items[0]).toContain('show in viewer');
    expect(items[1]).toContain('copy key');
  });

  it('remembers a fold under the lab\'s own key and reads it back in a fresh menu', async () => {
    const { menu } = await openBoth();
    const notes = labWidgets().find((w) => w.key === 'core.notes')!;
    groupHead(menu, notes.category).click();
    await settle();
    expect(groupHead(menu, notes.category).getAttribute('aria-expanded')).toBe('false');
    expect(JSON.parse(localStorage.getItem('devwidgetlab.tree.folds')!)).toEqual({ [notes.category]: false });
    while (mounted.length) unmount(mounted.pop()!);
    document.body.innerHTML = '';
    const again = await openBoth();
    expect(groupHead(again.menu, notes.category).getAttribute('aria-expanded')).toBe('false');
  });

  it('opens every group that still has a match while the filter is on, and leaves the stored folds alone', async () => {
    const { menu } = await openBoth();
    const field = menu.querySelector('input[type="search"]') as HTMLInputElement;
    field.value = 'a';
    field.dispatchEvent(new Event('input', { bubbles: true }));
    await settle();
    const heads = [...menu.querySelectorAll<HTMLButtonElement>('.dwl-tree .dwl-group')];
    expect(heads.length).toBeGreaterThan(2);
    expect(heads.every((head) => head.getAttribute('aria-expanded') === 'true')).toBe(true);
    expect(localStorage.getItem('devwidgetlab.tree.folds')).toBeNull();
  });

  it('draws a trailing "new items" group last, folded with a count of 0 while it is empty', async () => {
    const mountMenu = async (trailing: { id: string; label: string; leaves: { key: string; label: string }[] }[]): Promise<HTMLElement> => {
      const box = document.body.appendChild(document.createElement('div'));
      mounted.push(mount(LabMenu, { target: box, props: { trailing } }));
      await settle();
      return box;
    };
    const empty = await mountMenu([{ id: 'drafts', label: 'new items', leaves: [] }]);
    expect(empty.querySelector('.dwl-group[data-group="drafts"]')!.getAttribute('aria-expanded')).toBe('false');
    expect(empty.querySelector('.dwl-group[data-group="drafts"] .dwl-group-count')!.textContent).toBe('0');
    while (mounted.length) unmount(mounted.pop()!);
    document.body.innerHTML = '';
    const full = await mountMenu([{ id: 'drafts', label: 'new items', leaves: [{ key: 'draft.one', label: 'a draft' }] }]);
    const heads = [...full.querySelectorAll('.dwl-tree .dwl-group--nested')];
    expect(heads.at(-1)!.getAttribute('data-group')).toBe('drafts');
    expect(heads.at(-1)!.textContent).toContain('new items');
    expect(heads.at(-1)!.querySelector('.dwl-group-count')!.textContent).toBe('1');
  });

  it('has no widget / fit table switch in the viewer: the tree entry shows the fit table, a widget pick shows the widget', async () => {
    api.fitTableState.mockResolvedValue({ available: true, reason: '', running: false, started: null, exit: 1, table: SAMPLE_TABLE });
    const { menu, view } = await openBoth();
    expect(view.querySelector('.dwl-strip button[aria-pressed]')).toBeNull();
    expect([...view.querySelectorAll('.dwl-strip button')].map((b) => b.textContent)).not.toContain('fit table');
    menu.querySelector<HTMLButtonElement>('[data-all-fit]')!.click();
    await settle();
    expect(view.querySelector('.dwl-fit')).not.toBeNull();
    expect(menu.querySelector('[data-all-fit]')!.getAttribute('aria-current')).toBe('true');
    expect(view.querySelector('.dwl-strip-name')!.textContent).toBe('all widgets: fit table');
    leaf(menu, 'core.notes').click();
    await settle();
    expect(view.querySelector('.dwl-fit')).toBeNull();
    expect(frames(view).length).toBeGreaterThan(0);
  });
});
