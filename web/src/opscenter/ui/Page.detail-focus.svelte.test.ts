/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { createRawSnippet, flushSync, mount, unmount } from 'svelte';
import type { Snippet } from 'svelte';
import Page from './Page.svelte';

let app: ReturnType<typeof mount> | null = null;
afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.replaceChildren();
  document.head.querySelectorAll('style[data-test]').forEach((node) => node.remove());
});

/** A snippet that draws one fixed fragment. Inputs: html (str). Output: Snippet. */
const snip = (html: string): Snippet => createRawSnippet(() => ({ render: () => html }));

function narrowBody(): void {
  const style = document.createElement('style');
  style.dataset.test = '';
  style.textContent = '.oc-page__body--detail > .oc-page__scroll { display: none; }';
  document.head.append(style);
}

function showColumn(): { props: { detail: Snippet | undefined }; opener: HTMLButtonElement } {
  const props = $state<Record<string, unknown> & { detail: Snippet | undefined }>({
    title: 'Widgets', frame: 'column', children: snip('<button id="opener">open</button>'), detail: undefined, detailTitle: 'item one',
  });
  app = mount(Page, { target: document.body, props: props as unknown as Parameters<typeof Page>[1] });
  flushSync();
  const opener = document.getElementById('opener') as HTMLButtonElement;
  opener.focus();
  return { props, opener };
}

test('a detail that replaces the list takes the focus into its head, and hands it back to the opener on close', async () => {
  narrowBody();
  const { props, opener } = showColumn();
  props.detail = snip('<p>item</p>');
  flushSync();
  const head = document.querySelector('[data-frame-region=detail] [data-detail-focus]');
  expect(head).not.toBeNull();
  expect(document.activeElement).toBe(head);
  props.detail = undefined;
  flushSync();
  await Promise.resolve();
  expect(document.querySelector('[data-frame-region=detail]')).toBeNull();
  expect(document.activeElement).toBe(opener);
});

test('a detail beside the list leaves the focus where the user put it', async () => {
  const { props, opener } = showColumn();
  props.detail = snip('<p>item</p>');
  flushSync();
  expect(document.activeElement).toBe(opener);
  props.detail = undefined;
  flushSync();
  await Promise.resolve();
  expect(document.activeElement).toBe(opener);
});

test('the side sheet closes on a pick, not on a control that discloses more of the side', () => {
  app = mount(Page, {
    target: document.body,
    props: { title: 'Sessions', frame: 'nav', side: snip('<div><button id="more" aria-expanded="false">inactive</button><button id="pick">all</button></div>'), children: snip('<p>list</p>') },
  });
  flushSync();
  const side = document.querySelector('[data-frame-region=side]') as HTMLElement;
  (document.querySelector('.oc-page__picker [data-btn]') as HTMLElement).click();
  flushSync();
  expect(side.hasAttribute('data-open')).toBe(true);
  (document.getElementById('more') as HTMLElement).click();
  flushSync();
  expect(side.hasAttribute('data-open')).toBe(true);
  (document.getElementById('pick') as HTMLElement).click();
  flushSync();
  expect(side.hasAttribute('data-open')).toBe(false);
});
