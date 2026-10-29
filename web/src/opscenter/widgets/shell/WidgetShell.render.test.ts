/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

vi.mock('../../api/auth.svelte', () => ({
  auth: { state: 'unknown' },
  initAuth: () => {},
  ApiError: class extends Error {},
  authFetch: () => Promise.resolve({}),
}));

import ShellHost from './fixtures/ShellHost.svelte';
import { PROBE_WIDGET } from './fixtures/ShellProbe.svelte';
import { defineWidget, boundAction } from './define-widget.svelte';
import { declaredActionsFor } from '../menu/declared-actions.svelte';
import type { FrameHeader } from '../../shell/frame-header.svelte';
import { t } from '../../../lib/i18n/index.svelte';

function draw(props: Record<string, unknown> = {}) {
  const target = document.createElement('div');
  document.body.appendChild(target);
  let header: FrameHeader | undefined;
  const app = mount(ShellHost, { target, props: { ...props, onHeader: (one: FrameHeader | undefined) => (header = one) } });
  flushSync();
  return { target, app, header: () => header };
}

afterEach(() => {
  document.body.innerHTML = '';
});

describe('where the controls are drawn', () => {
  test('up in the header while it is drawn, in the body bar when it is not', () => {
    const { target, app, header } = draw({ hostId: 'probe-host' });
    expect(target.querySelector('[data-widget-controls="body"] [data-probe-controls="body"]')).not.toBeNull();
    expect(header()?.action).toBeNull();

    header()!.drawn = true;
    flushSync();
    expect(target.querySelector('[data-probe-header] [data-probe-controls="header"]')).not.toBeNull();
    expect(target.querySelector('[data-widget-controls]')).toBeNull();

    header()!.drawn = false;
    flushSync();
    expect(header()?.action).toBeNull();
    expect(target.querySelector('[data-widget-controls="body"]')).not.toBeNull();
    unmount(app, { outro: false });
  });

  test('in the corner under a titleless host, and in a bar with no host at all', () => {
    const corner = draw({ titleless: true });
    expect(corner.target.querySelector('.oc-wshell-corner[data-widget-controls="corner"] [data-probe-controls="corner"]')).not.toBeNull();
    unmount(corner.app, { outro: false });

    const alone = draw();
    expect(alone.target.querySelector('.oc-wshell-bar [data-probe-controls="body"]')).not.toBeNull();
    unmount(alone.app, { outro: false });
  });

  test('a cell with no controls draws no bar, and the shell never offers a menu of its own', () => {
    const { target, app } = draw({ hostId: 'probe-host', withControls: false });
    expect(target.querySelector('[data-widget-controls]')).toBeNull();
    expect(target.querySelector('[aria-haspopup]')).toBeNull();
    unmount(app, { outro: false });
  });
});

describe('the states', () => {
  test('a non-ready status prints one sentence in place of the body: the cell note, else the catalog', () => {
    const own = draw({ status: 'empty', note: 'no tasks in this session' });
    expect(own.target.querySelector('[data-probe-body]')).toBeNull();
    expect(own.target.querySelector('[data-widget-note="empty"] .oc-state__title')?.textContent).toBe('no tasks in this session');
    unmount(own.app, { outro: false });

    const stock = draw({ status: 'loading' });
    const sentence = stock.target.querySelector('[data-widget-note="loading"]');
    expect(sentence?.querySelector('.oc-state__title')?.textContent).toBe(t('widget.state.loading'));
    expect(sentence?.textContent).not.toBe('widget.state.loading');
    expect(sentence?.getAttribute('role')).toBe('status');
    unmount(stock.app, { outro: false });

    const ready = draw();
    expect(ready.target.querySelector('[data-probe-body]')).not.toBeNull();
    expect(ready.target.querySelector('[data-widget-note]')).toBeNull();
    unmount(ready.app, { outro: false });
  });
});

describe('what reaches the widget menu', () => {
  test('the bound actions are declared on the host slot while mounted and withdrawn on unmount', () => {
    const runs: string[] = [];
    const { app } = draw({ hostId: 'probe-host', runs });
    const declared = declaredActionsFor('probe-host');
    expect(declared.map((one) => one.id)).toEqual(['mode:edit', 'save']);
    expect(declared[0]).toMatchObject({ label: t('opscenter.cell.notes.edit'), checked: true });
    expect(declared[1]).toMatchObject({ group: 'save' });
    expect(declared[1]?.checked).toBeUndefined();
    declared[1]?.run();
    expect(runs).toEqual(['save']);

    unmount(app, { outro: false });
    flushSync();
    expect(declaredActionsFor('probe-host')).toEqual([]);
  });
});

describe('defineWidget refuses a bad definition', () => {
  test('an action declared twice', () => {
    expect(() =>
      defineWidget({ id: 'probe.twice', scope: 'global', actions: [{ id: 'save', labelKey: 'x' }, { id: 'save', labelKey: 'y' }], state: {} }),
    ).toThrow(/save twice/);
  });

  test('a state name that is not flat lowercase', () => {
    const valid = (value: unknown): value is boolean => typeof value === 'boolean';
    expect(() =>
      defineWidget({ id: 'probe.name', scope: 'global', actions: [], state: { showPath: { home: 'device', default: false, valid } } }),
    ).toThrow(/showPath/);
  });

  test('a declared action left unbound', () => {
    expect(() => boundAction({ id: 'save', labelKey: 'x' }, undefined)).toThrow(/not bound/);
  });

  test('a good definition is frozen with its settings defaulted', () => {
    expect(Object.isFrozen(PROBE_WIDGET)).toBe(true);
    expect(PROBE_WIDGET.settings).toEqual({});
  });
});
