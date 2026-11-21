/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';

const blobCalls: string[] = [];
vi.mock('../../opscenter/api/auth.svelte', () => ({
  authFetchBlob: (path: string) => { blobCalls.push(path); return Promise.resolve(new Blob(['x'])); },
}));
vi.mock('../../opscenter/api/host', () => ({ openSession: () => true, openSessions: () => undefined }));

afterEach(() => { blobCalls.length = 0; vi.unstubAllGlobals(); });

test('downloadAttachment fetches through the authenticated door and clicks a blob link', async () => {
  const made = vi.fn(() => 'blob:x');
  vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: made, revokeObjectURL: () => undefined }));
  const clicked: string[] = [];
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) { clicked.push(this.download); });
  const { downloadAttachment } = await import('./run-actions');
  await downloadAttachment('run_ab', 'a b.csv');
  expect(blobCalls).toEqual(['/automations/runs/run_ab/attachments/a%20b.csv']);
  expect(clicked).toEqual(['a b.csv']);
  click.mockRestore();
}, 30000);
