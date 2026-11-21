/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import { ApiError } from '../../opscenter/api/auth.svelte';
import { setLocale } from '../i18n/index.svelte';
import LabelEditor from './LabelEditor.svelte';
import type { AbilitiesApi } from './abilities-api';

setLocale('en');

const puts: string[][] = [];
let refuse: Error | null = null;
const api: AbilitiesApi = {
  rescan: async () => { throw new Error('unused'); },
  putLabels: async (_m, labels) => { puts.push(labels); if (refuse) throw refuse; return labels; },
};
const mounted: ReturnType<typeof mount>[] = [];
const settle = async (): Promise<void> => { await new Promise((r) => setTimeout(r, 0)); flushSync(); };
const q = (sel: string): HTMLElement | null => document.body.querySelector<HTMLElement>(sel);

async function render(labels: string[]): Promise<void> {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(LabelEditor, { target, props: { machine: 'doom', labels, api } }));
  await settle();
}
async function type(text: string): Promise<void> {
  const input = q('[data-act="label-field"]') as HTMLInputElement;
  input.value = text;
  input.dispatchEvent(new Event('input', { bubbles: true }));
  await settle();
  q('[data-act="add-label"]')!.click();
  await settle(); await settle();
}

afterEach(async () => {
  for (const m of mounted.splice(0)) await unmount(m);
  document.body.replaceChildren();
  puts.length = 0; refuse = null;
});

describe('LabelEditor', () => {
  test('add then remove each send the whole list', async () => {
    await render(['fast disk']);
    await type('  RTX 4090 ');
    expect(puts).toEqual([['fast disk', 'rtx 4090']]);
    expect(document.body.textContent).toContain('rtx 4090');
    q('[data-label="fast disk"] [data-act="remove-label"]')!.click();
    await settle(); await settle();
    expect(puts[1]).toEqual(['rtx 4090']);
  });
  test('a 422 labels_invalid shows the catalog line and keeps the list', async () => {
    refuse = new ApiError('bad label: x', 422, 'labels_invalid', { detail: { code: 'labels_invalid', detail: 'bad label: x' } });
    await render([]);
    await type('bad!');
    const line = q('[data-act="labels-error"]')?.textContent ?? '';
    expect(line).toContain('one to 32 characters');
    expect(line).not.toContain('bad label: x');
    expect(q('[data-label]')).toBeNull();
  });
  test('a label already on the list sends nothing', async () => {
    await render(['fast disk']);
    await type('Fast Disk');
    expect(puts).toEqual([]);
  });
});
