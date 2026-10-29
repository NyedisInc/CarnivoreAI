/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import AlertDot from './AlertDot.svelte';
import { approvals } from '../approvals/approvals.svelte';
import type { ApprovalItem } from '../approvals/approvals-model';

const mounted: ReturnType<typeof mount>[] = [];

beforeEach(() => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ alerts: [], counts: { error: 0, warn: 0, info: 0 } }), { status: 200 })));
  approvals.items = [];
});

afterEach(async () => {
  for (const c of mounted.splice(0)) await unmount(c);
  vi.unstubAllGlobals();
  approvals.items = [];
});

test('a waiting permission approval lights the dot though no alert is raised', () => {
  mounted.push(mount(AlertDot, { target: document.body }));
  flushSync();
  expect(document.querySelector('[data-app-alert-dot]')).toBeNull();
  approvals.items = [{ id: 'perm', source: 'dialog', kind: 'permission', session_id: 'ses_perm', question: 'q?' } as ApprovalItem];
  flushSync();
  expect(document.querySelector('[data-app-alert-dot]')).not.toBeNull();
});
