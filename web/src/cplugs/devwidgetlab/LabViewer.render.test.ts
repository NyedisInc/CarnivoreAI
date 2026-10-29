/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const api = vi.hoisted(() => ({ labStatus: vi.fn(), runCapture: vi.fn(), fitTableState: vi.fn(), startMatrix: vi.fn() }));
vi.mock('./lab-api', async (importOriginal) => ({ ...(await importOriginal<typeof import('./lab-api')>()), ...api }));

import LabViewer from './LabViewer.svelte';
import { labWidgets } from '../sdk/widget-lab';
import { setLocale } from '../../lib/i18n/index.svelte';
import { SELECTION_KEY } from './lab-selection';
import { installLabBus, SAMPLE_TABLE } from './lab-test-bus';
import { readLabCss } from '../../lib/test-support/lab-css';

setLocale('en');

let app: ReturnType<typeof mount> | null = null;

/** Let promises, channel microtasks and effects settle. */
async function settle(): Promise<void> {
  for (let i = 0; i < 6; i += 1) {
    await Promise.resolve();
    await tick();
    flushSync();
  }
}

async function open(selection: Record<string, unknown> = {}, width = 0): Promise<HTMLElement> {
  Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, get: () => width });
  const notes = labWidgets().find((w) => w.key === 'core.notes')!;
  const zones = notes.hosts.map((h) => h.zone);
  localStorage.setItem(SELECTION_KEY, JSON.stringify({ selection: { widget: 'core.notes', hosts: zones, sizes: ['m'], theme: 'carnivore', fixture: 'data', menu: false, scenario: null, view: 'widget', focus: null, ...selection } }));
  app = mount(LabViewer, { target: document.body });
  await settle();
  return document.body;
}

const bands = (root: HTMLElement) => [...root.querySelectorAll<HTMLElement>('.dwl-host')];
const frames = (root: HTMLElement) => [...root.querySelectorAll<HTMLIFrameElement>('iframe.dwl-frame')];
const param = (frame: HTMLIFrameElement, name: string) => new URL(frame.src, 'http://x.test').searchParams.get(name);

beforeEach(() => {
  installLabBus();
  api.fitTableState.mockReset();
  api.fitTableState.mockResolvedValue({ available: true, reason: '', running: false, started: null, exit: null, table: null });
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
  delete (HTMLElement.prototype as { clientWidth?: unknown }).clientWidth;
});

describe('the viewer page', () => {
  it('draws one band per host on show, each frame at the host\'s published size, with no form control on the page', async () => {
    const root = await open();
    expect(bands(root).map((band) => band.dataset['host'])).toEqual(['home', 'terminal', 'drawer', 'drawer', 'drawer', 'popout']);
    expect(bands(root).filter((band) => band.dataset['host'] === 'drawer').map((band) => band.dataset['dock'])).toEqual(['left', 'bottom', 'right']);
    expect(param(frames(root)[0]!, 'widget')).toBe('core.notes');
    expect(param(frames(root)[0]!, 'size')).toBe('m');
    expect(new URL(frames(root)[0]!.src, 'http://x.test').pathname).toBe('/static/dist/widget-lab/index.html');
    expect(root.querySelector('.dwl-viewer')!.querySelectorAll('input, select:not([data-size-more]), textarea').length).toBe(0);
    expect(root.querySelector('.dwl-viewer')!.textContent).not.toMatch(/capture\b(?! \()/);
  });

  it('draws only the hosts and sizes the selection names, in the selected theme', async () => {
    const root = await open({ hosts: ['terminal'], sizes: ['m'], bandSizes: { terminal: 'l' }, theme: 'blade_runner' });
    expect(bands(root).map((band) => band.dataset['host'])).toEqual(['terminal']);
    expect(frames(root).map((f) => param(f, 'size'))).toEqual(['l']);
    expect(frames(root).every((f) => param(f, 'theme') === 'blade_runner')).toBe(true);
  });

  it('says in one dim line which hosts the widget does not declare, and draws no frame for them', async () => {
    const homeOnly = labWidgets().find((w) => w.hosts.some((h) => !h.supported))!;
    const root = await open({ widget: homeOnly.key, hosts: homeOnly.hosts.filter((h) => h.supported).map((h) => h.zone) });
    const lines = [...root.querySelectorAll('.dwl-undeclared')];
    expect(lines.length).toBe(homeOnly.hosts.filter((h) => !h.supported).length);
    expect(lines[0]!.textContent).toContain('not declared');
    expect(bands(root).every((band) => band.querySelector('iframe') !== null)).toBe(true);
  });

  it('applies a stored scenario to every frame and says so on the context line', async () => {
    const root = await open({ scenario: '{"GET /x": {"a": 1}}' });
    expect(frames(root).every((f) => param(f, 'scenario') === 'wait')).toBe(true);
    expect(root.querySelector('.dwl-context')!.textContent).toContain('scenario 1 routes');
  });

  it('writes the fit table\'s verdict on the caption and the reasons under the frame', async () => {
    api.fitTableState.mockResolvedValue({ available: true, reason: '', running: false, started: null, exit: 1, table: SAMPLE_TABLE });
    const root = await open();
    const term = bands(root).find((band) => band.dataset['host'] === 'terminal')!;
    expect(term.querySelector('.dwl-preview-cap .dwl-verdict')!.textContent).toBe('clip');
    expect(term.textContent).toContain('runs 5px past');
    const home = bands(root).find((band) => band.dataset['host'] === 'home')!;
    expect(home.querySelector('.dwl-preview-cap .dwl-verdict')!.textContent).toBe('pass');
    expect(root.querySelector('.dwl-strip .dwl-verdict')!.textContent).toBe('fail');
  });

  it('focuses a frame when its caption is pressed, dims the others, and Escape unfocuses', async () => {
    const root = await open();
    const caption = () => bands(root).find((band) => band.dataset['host'] === 'drawer')!.querySelector<HTMLButtonElement>('[data-cap-key]')!;
    caption().click();
    await settle();
    const previews = [...root.querySelectorAll<HTMLElement>('.dwl-preview')];
    expect(previews.filter((p) => p.dataset['focused'] === 'yes').length).toBe(1);
    expect(previews.filter((p) => p.dataset['dim'] === 'yes').length).toBe(previews.length - 1);
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
    await settle();
    expect(root.querySelectorAll('.dwl-preview[data-focused="yes"]').length).toBe(0);
  });

  it('names the page once: the strip shows the widget name and id, then the view switch, and no second "widget lab" label', async () => {
    const root = await open();
    const strip = root.querySelector('.dwl-strip')!;
    expect(strip.textContent).not.toMatch(/widget lab/i);
    const kids = [...strip.children].map((node) => node.className);
    expect(kids[0]).toContain('dwl-strip-name');
    expect(strip.querySelector('.dwl-hint')!.textContent).toBe('core.notes');
    expect(kids.findIndex((c) => c.includes('dwl-views'))).toBeGreaterThan(kids.findIndex((c) => c.includes('dwl-hint')));
  });

  it('boxes each frame at its published size, not the window (an m 384x256 is 384x256 plus the stage hairline)', async () => {
    const root = await open({ hosts: ['home'], sizes: ['m'] });
    const m = labWidgets().find((w) => w.key === 'core.notes')!.hosts.find((h) => h.zone === 'home')!.sizes.find((s) => s.name === 'm')!;
    const wrap = root.querySelector<HTMLElement>('.dwl-frame-wrap')!;
    expect(wrap.style.width).toBe(`${m.w}px`);
    expect(wrap.style.height).toBe(`${m.h}px`);
    expect(root.querySelector('.dwl-stage')!.contains(wrap)).toBe(true);
    expect(root.querySelector<HTMLElement>('.dwl-frame')!.style.margin).toBe('-16px');
  });

  it('always draws the mock bars (pop-out window bar, bottom widget bar)', async () => {
    const root = await open({ hosts: ['popout', 'terminal'], sizes: ['m'] });
    expect(root.querySelector('.dwl-chrome-window')).not.toBeNull();
    expect(root.querySelector('[data-bar="bottom"]')).not.toBeNull();
    expect(root.querySelector('.dwl-chrome-body')).not.toBeNull();
  });

  describe('the real left sidebar', () => {
    const bandOf = async (): Promise<HTMLElement> => {
      const root = await open({ hosts: ['drawer'], sizes: ['m'], docks: ['left'] });
      return root.querySelector<HTMLElement>('.dwl-host[data-host="drawer"]')!;
    };
    const frameOf = (band: HTMLElement) => band.querySelector<HTMLIFrameElement>('iframe.dwl-frame')!;
    const choose = async (band: HTMLElement, group: string, choice: string) => {
      band.querySelector<HTMLElement>(`[data-group="${group}"] [data-choice="${choice}"]`)!.click();
      for (let i = 0; i < 4; i += 1) { await Promise.resolve(); await tick(); flushSync(); }
    };

    it('draws the app\'s own sidebar in the frame (shell=sidebar) and no mock drawer around it', async () => {
      const band = await bandOf();
      const url = new URL(frameOf(band).src, 'http://x');
      expect(url.searchParams.get('shell')).toBe('sidebar');
      expect(url.searchParams.get('zone')).toBe('drawer');
      expect(band.querySelector('.dwl-dock, .dwl-dock--left, .dwl-dock-rows, [data-area-bar]')).toBeNull();
    });

    it('offers the real sidebar\'s states (width, folded, widget area, density) and no size switch', async () => {
      const band = await bandOf();
      expect([...band.querySelectorAll('[data-group]')].map((one) => one.getAttribute('data-group'))).toEqual(['width', 'fold', 'area', 'density']);
      expect(band.querySelector('.dwl-host-head [data-size-name]')).toBeNull();
      expect(band.querySelector('[data-group="area"] [aria-checked="true"]')!.getAttribute('data-choice')).toBe('full');
    });

    it('steps a state in the same loaded frame: the address never changes, as the real drawer keeps its widget mounted', async () => {
      const band = await bandOf();
      const frame = frameOf(band);
      const address = frame.src;
      await choose(band, 'area', 'glance');
      expect(band.querySelector('[data-group="area"] [aria-checked="true"]')!.getAttribute('data-choice')).toBe('glance');
      await choose(band, 'width', 'min');
      await choose(band, 'fold', 'on');
      await choose(band, 'density', 'detailed');
      expect(frameOf(band)).toBe(frame);
      expect(frame.src).toBe(address);
    });
  });

  it('has the pop-out key at the top right of the main viewer, as the home screen\'s float (and none in the pop-out window itself)', async () => {
    const root = await open();
    const key = root.querySelector<HTMLButtonElement>('.dwl-open-float > button[data-btn][data-tone="float"][data-lab-popout]');
    expect(key).not.toBeNull();
    expect(key!.getAttribute('aria-label')).toBe('pop the viewer out into its own window');
    expect(root.querySelector('.dwl-open-float')!.nextElementSibling!.matches('.dwl-strip')).toBe(true);
  });

  it('shows its own menu key only while the slide-out is closed', async () => {
    const root = await open();
    expect(root.querySelector('[data-lab-menu]')).not.toBeNull();
  });
});

describe('the fit table view', () => {
  async function openFit(over: Record<string, unknown> = {}): Promise<HTMLElement> {
    api.fitTableState.mockResolvedValue({ available: true, reason: '', running: false, started: null, exit: 1, table: SAMPLE_TABLE, ...over });
    const root = await open({ view: 'fit' });
    return root;
  }

  it('shows the counts, clip for clipping, and never a pass for a widget that could not be drawn; it has no run keys', async () => {
    const root = await openFit();
    expect(root.querySelector('[data-testid="fit-counts"]')!.textContent).toContain('1 pass, 2 fail, 1 not declared');
    const states = (widget: string) => [...root.querySelectorAll<HTMLElement>('[data-fit-cell]')].filter((c) => c.getAttribute('aria-label')!.startsWith(widget)).map((c) => c.dataset['state']);
    expect(states('core.notes')).toEqual(['pass', 'red']);
    expect(states('core.gone')).toEqual(['fail', 'fail']);
    expect([...root.querySelectorAll('button')].some((b) => /run matrix/.test(b.textContent ?? ''))).toBe(false);
  });

  it('a pressed cell picks widget, host and size, returns to the widget view and focuses that frame', async () => {
    const root = await openFit();
    (root.querySelector('[data-fit-cell][data-state="red"]') as HTMLButtonElement).click();
    await settle();
    expect(root.querySelector('.dwl-fit-table')).toBeNull();
    const focused = root.querySelector<HTMLElement>('.dwl-preview[data-focused="yes"]')!;
    expect(focused.closest<HTMLElement>('.dwl-host')!.dataset['host']).toBe('terminal');
    expect(focused.dataset['size']).toBe('m');
    expect(JSON.parse(localStorage.getItem(SELECTION_KEY)!).selection.focus).toEqual({ host: 'terminal', size: 'm' });
    expect(JSON.parse(localStorage.getItem(SELECTION_KEY)!).selection.bandSizes).toEqual({ terminal: 'm' });
  });

  it('says a run that could not determine is not a result', async () => {
    const root = await openFit({ exit: 2 });
    expect(root.textContent).toContain('nothing here is a pass');
  });
});

describe('the phone-wide page', () => {
  for (const theme of ['carnivore', 'blade_runner']) {
    it(`shows one host at a time as tabs with the frames scaled down to fit, under ${theme}`, async () => {
      const root = await open({ theme }, 400);
      expect(root.querySelector('.dwl')!.getAttribute('data-phone')).toBe('yes');
      expect([...root.querySelectorAll('.dwl-hosttabs [role="radio"]')].length).toBe(4);
      expect(bands(root).length).toBe(1);
      expect(frames(root).every((f) => param(f, 'theme') === theme)).toBe(true);
      expect(Number(root.querySelector<HTMLElement>('.dwl-zoom')!.dataset['scale'])).toBeLessThan(1);
      (root.querySelectorAll('.dwl-hosttabs [role="radio"]')[1] as HTMLButtonElement).click();
      await settle();
      expect(bands(root).map((band) => band.dataset['host'])).toEqual(['terminal']);
    });
  }

  it('stays at true size when the page is wide', async () => {
    const root = await open({}, 1200);
    expect(root.querySelector('.dwl')!.getAttribute('data-phone')).toBe('no');
    expect(root.querySelector<HTMLElement>('.dwl-zoom')!.dataset['scale']).toBe('1.00');
  });
});

describe('the host chrome', () => {
  const css = readLabCss();
  const rule = (selector: string): string => css.slice(css.indexOf(`${selector} {`), css.indexOf('}', css.indexOf(`${selector} {`)));

  it('draws each host in its own chrome: the terminal grid its bottom bar, the pop-out a window bar, the drawer the real LEFT sidebar by default', async () => {
    const root = await open({ sizes: ['m'] });
    const chrome = (host: string) => root.querySelector<HTMLElement>(`.dwl-host[data-host="${host}"] .dwl-chrome`)!;
    const drawer = chrome('drawer');
    expect(drawer.dataset['chrome']).toBe('drawer');
    expect(drawer.dataset['dock']).toBe('left');
    expect(drawer.querySelector('.dwl-dock')).toBeNull();
    expect(new URL(drawer.querySelector<HTMLIFrameElement>('iframe.dwl-frame')!.src, 'http://x').searchParams.get('shell')).toBe('sidebar');
    expect(chrome('terminal').querySelector('nav.rail--bottom .rail__layer')).not.toBeNull();
    expect(chrome('home').querySelector('.dwl-dock, .rail--bottom')).toBeNull();
    expect(chrome('popout').querySelector('.dwl-chrome-window')).not.toBeNull();
    expect(chrome('drawer').querySelector('iframe.dwl-frame')).not.toBeNull();
  });

  it('draws the drawer in each of the three real drawers: the left widget area, the right slide-out beside its bar, the bottom slide-out above its bar', async () => {
    const dockOf = async (dock: string): Promise<HTMLElement> => {
      document.body.innerHTML = '';
      if (app) unmount(app);
      const root = await open({ hosts: ['drawer'], sizes: ['m'], docks: [dock] });
      return root.querySelector<HTMLElement>('.dwl-host[data-host="drawer"] .dwl-chrome')!;
    };
    const left = await dockOf('left');
    expect(left.querySelector('iframe.dwl-frame')).not.toBeNull();
    expect(left.querySelector('.dwl-dock, .rail__layer')).toBeNull();
    const right = await dockOf('right');
    expect(right.dataset['dock']).toBe('right');
    expect(right.querySelector('.dwl-dock-panel--side .rail-grip--side[data-rail-grip="side"]')).not.toBeNull();
    expect(right.querySelector('.dwl-dock-panel--side iframe.dwl-frame')).not.toBeNull();
    expect(right.querySelector('nav.rail:not(.rail--bottom) .rail__layer [data-key-open]')).not.toBeNull();
    const bottom = await dockOf('bottom');
    expect(bottom.dataset['dock']).toBe('bottom');
    expect(bottom.querySelector('.dwl-dock-panel--bottom .rail-grip--bottom[data-rail-grip="bottom"]')).not.toBeNull();
    expect(bottom.querySelector('nav.rail--bottom .rail__layer [data-key-open]')).not.toBeNull();
    expect(bottom.querySelector('.dwl-dock-panel')!.nextElementSibling!.matches('nav.rail--bottom')).toBe(true);
  });

  it('names the drawer band for the drawer it is drawn in', async () => {
    const root = await open({ hosts: ['drawer'], sizes: ['m'], docks: ['bottom'] });
    expect(root.querySelector('.dwl-host[data-host="drawer"] .dwl-host-name')!.textContent).toBe('bottom drawer');
  });

  it('keeps the drawers and their stage square: no rounded rectangle anywhere in the chrome rules', () => {
    for (const selector of ['.dwl-chrome--drawer', '.dwl-dock', '.dwl-dock-panel']) expect(rule(selector)).not.toMatch(/border-radius/);
    expect(rule('.dwl-chrome')).toMatch(/border-radius: 0/);
    expect(rule('.dwl-stage')).toMatch(/border-radius: 0/);
  });
});

describe('free resize', () => {
  const dims = (root: HTMLElement) => root.querySelector('.dwl-host[data-host="home"] [data-testid="dims"]')!.textContent!.replace(/\s+/g, ' ').trim();
  const handle = (root: HTMLElement, edge: string) => root.querySelector<HTMLElement>(`.dwl-host[data-host="home"] .dwl-handle--${edge}`)!;
  const key = (el: HTMLElement, name: string, shiftKey = false) => el.dispatchEvent(new KeyboardEvent('keydown', { key: name, shiftKey, bubbles: true, cancelable: true }));

  it('starts at the published size and shows its W x H with the nearest named size', async () => {
    const root = await open({ hosts: ['home'], sizes: ['m'] });
    const m = labWidgets().find((w) => w.key === 'core.notes')!.hosts.find((h) => h.zone === 'home')!.sizes.find((s) => s.name === 'm')!;
    expect(dims(root)).toContain(`${m.w} x ${m.h}`);
    expect(dims(root)).toContain('nearest m');
    expect(root.querySelector('[data-reset]')).toBeNull();
  });

  it('arrow keys on a handle change the frame size, the frame is redrawn at that box, and reset restores the published size', async () => {
    const root = await open({ hosts: ['home'], sizes: ['m'] });
    const m = labWidgets().find((w) => w.key === 'core.notes')!.hosts.find((h) => h.zone === 'home')!.sizes.find((s) => s.name === 'm')!;
    key(handle(root, 'e'), 'ArrowRight', true);
    key(handle(root, 's'), 'ArrowDown');
    await settle();
    expect(dims(root)).toContain(`${m.w + 32} x ${m.h! + 8}`);
    expect(root.querySelector('[data-reset]')!.textContent).toBe('reset to m');
    await new Promise((resolve) => setTimeout(resolve, 500));
    await settle();
    const frame = frames(root)[0]!;
    expect(param(frame, 'w')).toBe(String(m.w + 32));
    expect(param(frame, 'h')).toBe(String(m.h! + 8));
    expect(root.querySelector('.dwl-resize')!.getAttribute('data-live')).toBe('no');
    root.querySelector<HTMLButtonElement>('[data-reset]')!.click();
    await settle();
    expect(dims(root)).toContain(`${m.w} x ${m.h}`);
    expect(param(frames(root)[0]!, 'w')).toBeNull();
    expect(root.querySelector('[data-reset]')).toBeNull();
  });

  it('marks the fit verdict "for <size>" once the frame is no longer the published box', async () => {
    api.fitTableState.mockResolvedValue({ available: true, reason: '', running: false, started: null, exit: 1, table: SAMPLE_TABLE });
    const root = await open({ hosts: ['home'], sizes: ['m'] });
    const verdict = () => root.querySelector('.dwl-host[data-host="home"] .dwl-preview-cap .dwl-verdict')!.textContent;
    expect(verdict()).toBe('pass');
    key(handle(root, 'e'), 'ArrowLeft');
    await settle();
    expect(verdict()).toBe('pass for m');
  });
});

describe('the right and bottom drawers fill the panel body', () => {
  const key = (el: HTMLElement, name: string, shiftKey = false) => el.dispatchEvent(new KeyboardEvent('keydown', { key: name, shiftKey, bubbles: true, cancelable: true }));
  const css = readLabCss();
  const panel = (root: HTMLElement, dock: 'side' | 'bottom') => root.querySelector<HTMLElement>(`.dwl-host[data-host="drawer"] .dwl-dock-panel--${dock}`)!;

  it('draws the right panel at the real default, 378 x 800, the frame as the whole body with no card box and no rounded corner', async () => {
    const root = await open({ hosts: ['drawer'], sizes: ['s', 'm', 'l'], docks: ['right'] });
    const body = panel(root, 'side').querySelector<HTMLElement>('.dwl-dock-slot')!;
    expect(body.children).toHaveLength(1);
    expect(body.querySelector('.dwl-card, .oc-card, .oc-frame')).toBeNull();
    const frame = frames(root);
    expect(frame).toHaveLength(1);
    expect(param(frame[0]!, 'dock')).toBe('side');
    expect(param(frame[0]!, 'w')).toBe('378');
    expect(param(frame[0]!, 'h')).toBe('800');
    expect(body.querySelector<HTMLElement>('.dwl-frame-wrap')!.dataset['box']).toBe('378x800');
    expect(css).not.toMatch(/\.dwl-dock-slot\s*\{[^}]*border-radius/);
    expect(css).not.toMatch(/\.dwl-frame-wrap\s*\{[^}]*border-radius/);
  });

  it('draws the bottom panel at the real default height and the strip\'s full width, 1244 x 318', async () => {
    const root = await open({ hosts: ['drawer'], sizes: ['m'], docks: ['bottom'] });
    const frame = frames(root)[0]!;
    expect(param(frame, 'dock')).toBe('bottom');
    expect(param(frame, 'w')).toBe('1244');
    expect(param(frame, 'h')).toBe('318');
    expect(panel(root, 'bottom').querySelector<HTMLElement>('.dwl-frame-wrap')!.dataset['box']).toBe('1244x318');
  });

  it('leaves the left drawer and the grids at their published sizes (no dock in the frame query)', async () => {
    const root = await open({ hosts: ['drawer', 'home'], sizes: ['m'], docks: ['left'] });
    for (const frame of frames(root)) expect(param(frame, 'dock')).toBeNull();
  });

  it('resizes the right panel from its inner edge: only the width changes, the frame is redrawn at the new box, reset returns to the default panel', async () => {
    const root = await open({ hosts: ['drawer'], sizes: ['m'], docks: ['right'] });
    const edge = root.querySelector<HTMLElement>('.dwl-handle--w')!;
    expect(root.querySelector('.dwl-handle--e, .dwl-handle--s, .dwl-handle--se')).toBeNull();
    key(edge, 'ArrowLeft', true);
    key(edge, 'ArrowDown');
    await settle();
    expect(root.querySelector('[data-testid="dims"]')!.textContent).toContain('410 x 800');
    await new Promise((resolve) => setTimeout(resolve, 500));
    await settle();
    expect(param(frames(root)[0]!, 'w')).toBe('410');
    expect(param(frames(root)[0]!, 'h')).toBe('800');
    expect(param(frames(root)[0]!, 'dock')).toBe('side');
    expect(root.querySelector('[data-reset]')!.textContent).toBe('reset to the default panel');
    root.querySelector<HTMLButtonElement>('[data-reset]')!.click();
    await settle();
    expect(param(frames(root)[0]!, 'w')).toBe('378');
  });

  it('resizes the bottom panel from its inner edge: only the height changes, ArrowUp grows it', async () => {
    const root = await open({ hosts: ['drawer'], sizes: ['m'], docks: ['bottom'] });
    const edge = root.querySelector<HTMLElement>('.dwl-handle--n')!;
    key(edge, 'ArrowUp', true);
    key(edge, 'ArrowRight');
    await settle();
    expect(root.querySelector('[data-testid="dims"]')!.textContent).toContain('1,244 x 350');
    await new Promise((resolve) => setTimeout(resolve, 500));
    await settle();
    expect(param(frames(root)[0]!, 'h')).toBe('350');
    expect(param(frames(root)[0]!, 'w')).toBe('1244');
  });
});

describe('per-band size switches', () => {
  const band = (root: HTMLElement, zone: string) => root.querySelector<HTMLElement>(`.dwl-host[data-host="${zone}"]`)!;
  const keys = (root: HTMLElement, zone: string) => [...band(root, zone).querySelectorAll<HTMLButtonElement>('.dwl-band-sizes [role="radio"][data-size-name]')];
  const lit = (root: HTMLElement, zone: string) => keys(root, zone).filter((key) => key.getAttribute('aria-checked') === 'true').map((key) => key.dataset['sizeName']);
  const sizeOf = (root: HTMLElement, zone: string) => param(band(root, zone).querySelector<HTMLIFrameElement>('iframe.dwl-frame')!, 'size');

  it('puts s, m and l in each band\'s header beside the host name, the current one lit, and the rest behind a small "more" menu', async () => {
    const root = await open({ hosts: ['home', 'terminal'], sizes: ['m'] });
    const head = band(root, 'home').querySelector('.dwl-host-head')!;
    expect([...head.children].slice(0, 2).map((node) => node.className)).toEqual(['dwl-host-name', 'dwl-band-sizes']);
    expect(keys(root, 'home').map((key) => key.dataset['sizeName'])).toEqual(['s', 'm', 'l']);
    expect(lit(root, 'home')).toEqual(['m']);
    const rest = [...band(root, 'home').querySelectorAll<HTMLOptionElement>('[data-size-more] option[data-size-name]')].map((key) => key.dataset['sizeName']);
    expect(rest.length).toBeGreaterThan(0);
    expect(rest.some((name) => ['s', 'm', 'l'].includes(name!))).toBe(false);
  });

  it('switches only that band: its frame is redrawn at the new size, the other band stays, and the choice is remembered with the selection', async () => {
    const root = await open({ hosts: ['home', 'terminal'], sizes: ['m'] });
    keys(root, 'home').find((key) => key.dataset['sizeName'] === 'l')!.click();
    await settle();
    expect(sizeOf(root, 'home')).toBe('l');
    expect(sizeOf(root, 'terminal')).toBe('m');
    expect(lit(root, 'home')).toEqual(['l']);
    expect(frames(root)).toHaveLength(2);
    expect(JSON.parse(localStorage.getItem(SELECTION_KEY)!).selection.bandSizes).toEqual({ home: 'l' });
    unmount(app!);
    document.body.innerHTML = '';
    app = mount(LabViewer, { target: document.body });
    await settle();
    expect(sizeOf(document.body, 'home')).toBe('l');
    expect(sizeOf(document.body, 'terminal')).toBe('m');
  });

  it('switches a size that lives behind "more", and shows no switches in the right and bottom drawers', async () => {
    const root = await open({ hosts: ['home', 'drawer'], sizes: ['m'], docks: ['left'] });
    const more = band(root, 'home').querySelector<HTMLSelectElement>('[data-size-more]')!;
    more.value = 'phone';
    more.dispatchEvent(new Event('change', { bubbles: true }));
    await settle();
    expect(sizeOf(root, 'home')).toBe('phone');
    expect(band(root, 'home').querySelector<HTMLSelectElement>('[data-size-more]')!.value).toBe('phone');
    document.body.innerHTML = '';
    unmount(app!);
    const right = await open({ hosts: ['drawer'], sizes: ['m'], docks: ['right'] });
    expect(right.querySelector('.dwl-band-sizes')).toBeNull();
  });
});
