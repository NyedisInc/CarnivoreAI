/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { inputFocus } from '../../lib/input-focus.svelte';
import { PRIMARY_SLOT } from '../../engine/model';
import { registerTabGroup, stepActiveTabs } from './tab-step';
import { APP_CHORDS } from '../../../lib/app-keys/chords';
import { installAppKeys } from '../../../lib/app-keys/router';

let stops: Array<() => void> = [];
afterEach(() => { stops.forEach((s) => s()); stops = []; });

function group(instance: string, tabs: string[], active: string) {
  const state = { active, select: vi.fn((tab: string) => { state.active = tab; }) };
  stops.push(registerTabGroup(instance, { tabs: () => tabs, active: () => state.active, select: state.select }));
  return state;
}

test('next and previous move the active tab and wrap at both ends', () => {
  const g = group('terminal:a', ['terminal:row:1', 'terminal:row:2', 'terminal:row:3'], 'terminal:row:2');
  inputFocus.claim('terminal:row:2');
  expect(stepActiveTabs(1)).toBe(true);
  expect(g.active).toBe('terminal:row:3');
  stepActiveTabs(1);
  expect(g.active).toBe('terminal:row:1');
  stepActiveTabs(-1);
  expect(g.active).toBe('terminal:row:3');
});

test('acts on the group holding input, else the one last selected, never the other', () => {
  const a = group('terminal:a', ['terminal:row:1', 'terminal:row:2'], 'terminal:row:1');
  const b = group('terminal:b', ['terminal:row:3', 'terminal:row:4'], 'terminal:row:3');
  inputFocus.claim('terminal:row:3');
  stepActiveTabs(1);
  expect(b.select).toHaveBeenCalledWith('terminal:row:4');
  inputFocus.forget('terminal:row:3');
  inputFocus.select('terminal:row:1');
  stepActiveTabs(1);
  expect(a.select).toHaveBeenCalledWith('terminal:row:2');
});

test('a one-tab group does nothing and no component on screen lets the key through', () => {
  const g = group('terminal:a', ['terminal:row:9'], 'terminal:row:9');
  inputFocus.claim('terminal:row:9');
  expect(stepActiveTabs(1)).toBe(true);
  expect(g.select).not.toHaveBeenCalled();
  stops.forEach((s) => s()); stops = [];
  expect(stepActiveTabs(1)).toBe(true);
});

const press = (init: KeyboardEventInit, target: Element = document.body) => {
  const e = new KeyboardEvent('keydown', { bubbles: true, cancelable: true, ...init });
  target.dispatchEvent(e);
  return e;
};
const PREV = { key: '<', code: 'Comma', metaKey: true, shiftKey: true };

test('with owner and selected cleared the page terminal steps and the key is claimed', () => {
  inputFocus.forget('terminal:row:1'); inputFocus.forget('terminal:row:2');
  const g = group(PRIMARY_SLOT, ['terminal:row:1', 'terminal:row:2'], 'terminal:row:1');
  stops.push(installAppKeys(APP_CHORDS, document));
  expect(press(PREV).defaultPrevented).toBe(true);
  expect(g.active).toBe('terminal:row:2');
});

test('with no group registered both chords are still claimed, from a text field too', () => {
  stops.push(installAppKeys(APP_CHORDS, document));
  const input = document.body.appendChild(document.createElement('input'));
  expect(press(PREV).defaultPrevented).toBe(true);
  expect(press({ key: '>', code: 'Period', metaKey: true, shiftKey: true }, input).defaultPrevented).toBe(true);
  input.remove();
});

test('focus inside another group steps that group, not the primary', () => {
  const p = group(PRIMARY_SLOT, ['terminal:row:1', 'terminal:row:2'], 'terminal:row:1');
  const o = group('terminal:other', ['terminal:row:7', 'terminal:row:8'], 'terminal:row:7');
  const tg = document.body.appendChild(document.createElement('div'));
  tg.className = 'oc-tg';
  tg.innerHTML = '<button data-tab="terminal:row:7"></button><button data-tab="terminal:row:8"></button>';
  (tg.firstElementChild as HTMLElement).focus();
  stepActiveTabs(1);
  tg.remove();
  expect(o.active).toBe('terminal:row:8');
  expect(p.select).not.toHaveBeenCalled();
});

test('the chord is cmd+< and cmd+> on the Comma and Period keys, and cmd+comma alone is not it', () => {
  const g = group('terminal:a', ['terminal:row:1', 'terminal:row:2'], 'terminal:row:1');
  inputFocus.claim('terminal:row:1');
  stops.push(installAppKeys(APP_CHORDS, document));
  const press = (init: KeyboardEventInit) => {
    const e = new KeyboardEvent('keydown', { bubbles: true, cancelable: true, ...init });
    document.body.dispatchEvent(e);
    return e;
  };
  expect(press({ key: ',', code: 'Comma', metaKey: true }).defaultPrevented).toBe(false);
  expect(g.select).not.toHaveBeenCalled();
  const hit = press({ key: ';', code: 'Comma', metaKey: true, shiftKey: true });
  expect(hit.defaultPrevented).toBe(true);
  expect(g.active).toBe('terminal:row:2');
  press({ key: '>', code: 'Period', metaKey: true, shiftKey: true });
  expect(g.active).toBe('terminal:row:1');
});
