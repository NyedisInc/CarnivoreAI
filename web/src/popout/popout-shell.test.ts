/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import PopoutBarActions from '../opscenter/shell/PopoutBarActions.svelte';
import { editorSeams, finishLayoutEditor, layoutEditor } from '../opscenter/layout-editor/editor.svelte';
import { usePopoutEditorSeams } from '../opscenter/layout-editor/popout-editor';
import { viewport } from '../opscenter/engine/viewport.svelte';
import { setLocale } from '../lib/i18n/index.svelte';

setLocale('en');

function ruleFor(selector: string): string {
  const css = fs.readFileSync(path.resolve(__dirname, 'popout.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
  const at = css.indexOf(`${selector} {`);
  expect(at, `${selector} has a rule`).toBeGreaterThan(-1);
  return css.slice(at, css.indexOf('}', at));
}

test('the window is ONE scroller: #popout-screen is a flex column that scrolls, the page itself never does', () => {
  const screen = ruleFor('#popout-screen');
  expect(screen).toMatch(/display:\s*flex/);
  expect(screen).toMatch(/flex-direction:\s*column/);
  expect(screen).toMatch(/overflow-y:\s*auto/);
  expect(screen).toMatch(/height:\s*100%/);
  expect(ruleFor('html[data-popout], html[data-popout] body')).toMatch(/overflow:\s*hidden/);
  const app = fs.readFileSync(path.resolve(__dirname, '../opscenter/app.css'), 'utf8');
  expect(app).toMatch(/\.oc-app \{[^}]*flex: 1 1 auto;/);
});

const real = { ...editorSeams };
const mounted: ReturnType<typeof mount>[] = [];

beforeEach(() => {
  usePopoutEditorSeams();
});

afterEach(async () => {
  if (layoutEditor.active) finishLayoutEditor();
  for (const c of mounted.splice(0)) await unmount(c);
  Object.assign(editorSeams, real);
  viewport.wide = true;
  document.body.replaceChildren();
  window.history.replaceState(null, '', '/');
  vi.restoreAllMocks();
});

function bar(search: string): HTMLElement {
  window.history.replaceState(null, '', `/static/popout.html${search}`);
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(PopoutBarActions, { target }));
  flushSync();
  return target;
}

test('a dashboard pop-out shows "edit layout" in its bar, and pressing it turns edit layout on', () => {
  viewport.wide = true;
  const root = bar('?board=b-2&edit=1');
  const edit = root.querySelector<HTMLButtonElement>('[data-popout-edit-layout]')!;
  expect(edit.textContent?.trim()).toBe('edit layout');
  expect(edit.disabled).toBe(false);
  edit.click();
  flushSync();
  expect(layoutEditor.active).toBe(true);
  expect(root.querySelector('[data-popout-edit-layout]')).toBeNull();
});

test('the button is live even when the bar mounts BEFORE the editor is pointed at the board (the old hidden-forever bug)', () => {
  Object.assign(editorSeams, real);
  viewport.wide = true;
  const root = bar('?board=b-2&edit=1');
  usePopoutEditorSeams();
  flushSync();
  const edit = root.querySelector<HTMLButtonElement>('[data-popout-edit-layout]')!;
  expect(edit.disabled).toBe(false);
  edit.click();
  flushSync();
  expect(layoutEditor.active).toBe(true);
});

test('a narrow dashboard pop-out still shows the button, disabled, saying why', () => {
  viewport.wide = false;
  const edit = bar('?board=b-2&edit=1').querySelector<HTMLButtonElement>('[data-popout-edit-layout]')!;
  expect(edit.disabled).toBe(true);
  expect(edit.title).toBe('widen the window to edit layout');
});

test('NEGATIVE: a plain home pop-out or a wallboard has no edit control', () => {
  expect(bar('').querySelector('[data-popout-edit-layout]')).toBeNull();
  expect(bar('?view=wallboard&board=b-2').querySelector('[data-popout-edit-layout]')).toBeNull();
});
