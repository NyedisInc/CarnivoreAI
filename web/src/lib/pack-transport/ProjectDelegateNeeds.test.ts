/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import ProjectDelegateNeeds from './ProjectDelegateNeeds.svelte';
import type { NeedsApi, NeedsBody, NeedsView } from './needs-api';
import { setLocale } from '../i18n/index.svelte';

setLocale('en');

const puts: NeedsBody[] = [];
let doc: NeedsView;
const fresh = (): NeedsView => ({
  vocabulary: ['xcode', 'gpu:nvidia', 'label:<text>'],
  kinds: {
    render: { needs: ['gpu:nvidia'], prefer: [], stored: true, default_filters: ['gpu'], default_prefer: [] },
    browser: { needs: [], prefer: [], stored: false, default_filters: [], default_prefer: ['xcode'] },
  },
});
const api: NeedsApi = {
  read: async () => structuredClone(doc),
  write: async (_n, body) => {
    puts.push(body);
    for (const [kind, v] of Object.entries(body)) doc.kinds[kind] = v ? { ...doc.kinds[kind]!, ...v, stored: true } : { ...doc.kinds[kind]!, needs: [], prefer: [], stored: false };
  },
};
const mounted: ReturnType<typeof mount>[] = [];
const settle = async (): Promise<void> => { await new Promise((r) => setTimeout(r, 0)); flushSync(); };
async function render(): Promise<HTMLElement> {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(ProjectDelegateNeeds, { target, props: { name: 'notes', api } }));
  await settle();
  return target;
}
const kind = (root: HTMLElement, k: string): HTMLElement => root.querySelector<HTMLElement>(`[data-kind="${k}"]`)!;
const type = (el: HTMLInputElement, v: string): void => { el.value = v; el.dispatchEvent(new Event('input', { bubbles: true })); flushSync(); };

beforeEach(() => { puts.length = 0; doc = fresh(); });
afterEach(() => { mounted.splice(0).forEach((m) => void unmount(m)); document.body.replaceChildren(); });

describe('the project needs block', () => {
  test('draws a row per kind of the GET and its vocabulary, with the default beside an unstored kind', async () => {
    const root = await render();
    expect([...root.querySelectorAll('[data-pt="needs-kind"]')].map((e) => e.getAttribute('data-kind'))).toEqual(['render', 'browser']);
    expect(root.querySelector('[data-pt="needs-vocab"]')!.textContent).toContain('gpu:nvidia, label:<text>');
    expect(kind(root, 'browser').querySelector('[data-pt="needs-default"]')!.textContent).toContain('prefer xcode');
    expect(root.querySelector<HTMLButtonElement>('[data-pt="needs-save"]')!.disabled).toBe(true);
  });

  test('save sends only the kinds that changed', async () => {
    const root = await render();
    type(kind(root, 'browser').querySelector<HTMLInputElement>('[data-pt="needs-input"]')!, 'xcode, os:macos');
    root.querySelector<HTMLButtonElement>('[data-pt="needs-save"]')!.click();
    await settle();
    expect(puts).toEqual([{ browser: { needs: ['xcode', 'os:macos'], prefer: [] } }]);
  });

  test('back to default sends null for that kind and the default shows again', async () => {
    const root = await render();
    kind(root, 'render').querySelector<HTMLButtonElement>('[data-pt="needs-reset"]')!.click();
    await settle();
    expect(puts).toEqual([{ render: null }]);
    expect(kind(root, 'render').querySelector('[data-pt="needs-default"]')!.textContent).toContain('needs gpu');
    expect(kind(root, 'render').querySelector<HTMLInputElement>('[data-pt="needs-input"]')!.value).toBe('');
  });
});
