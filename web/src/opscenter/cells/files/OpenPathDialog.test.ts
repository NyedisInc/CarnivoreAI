/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import { ApiError } from '../../api/auth.svelte';

const fake = vi.hoisted(() => ({ outcome: null as unknown }));

vi.mock('../../../lib/file-drawer/tree-api', () => ({
  openPathInFilesList: () => (fake.outcome ? Promise.reject(fake.outcome) : Promise.resolve()),
}));

import OpenPathDialog from './OpenPathDialog.svelte';

let handle: ReturnType<typeof mount> | null = null;

afterEach(() => {
  if (handle) unmount(handle);
  handle = null;
  document.body.innerHTML = '';
  fake.outcome = null;
});

async function submitPath(): Promise<ReturnType<typeof vi.fn>> {
  const onOpened = vi.fn();
  handle = mount(OpenPathDialog, { target: document.body, props: { open: true, onOpened } });
  flushSync();
  const field = document.querySelector<HTMLInputElement>('.files-path-form input')!;
  field.value = '/tmp/missing.md';
  field.dispatchEvent(new Event('input', { bubbles: true }));
  flushSync();
  document.querySelector<HTMLFormElement>('.files-path-form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  await new Promise((resolve) => setTimeout(resolve, 0));
  flushSync();
  return onOpened;
}

describe('open path dialog', () => {
  test('a refused open shows the server reason and stays open', async () => {
    fake.outcome = new ApiError('HTTP 404', 404, null, { detail: { detail: 'that file is not there' } });
    const onOpened = await submitPath();
    expect(document.body.textContent).toContain('that file is not there');
    expect(document.querySelector('.files-path-form')).not.toBeNull();
    expect(onOpened).not.toHaveBeenCalled();
  });

  test('an accepted open closes the dialog and tells the host', async () => {
    const onOpened = await submitPath();
    expect(onOpened).toHaveBeenCalledTimes(1);
    expect(document.querySelector('.files-path-form')).toBeNull();
  });
});

describe('the dialog words', () => {
  test('every string the dialog draws is catalog copy, never a raw key', () => {
    handle = mount(OpenPathDialog, { target: document.body, props: { open: true, onOpened: vi.fn() } });
    flushSync();
    const dialog = document.querySelector('.files-path-form')!;
    const input = dialog.querySelector('input')!;
    const drawn = [document.body.textContent ?? '', input.getAttribute('placeholder') ?? '', input.getAttribute('aria-label') ?? ''].join(' ');
    expect(drawn).not.toMatch(/opscenter\.cell\.files\./);
    expect(document.body.textContent).toContain('open a file path');
    expect(input.getAttribute('placeholder')).toContain('/path/to/file.md');
    expect(document.body.textContent).toContain('open file');
  });
});
