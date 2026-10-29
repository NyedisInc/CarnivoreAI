/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import TaskManagerMarkdown from './TaskManagerMarkdown.svelte';
import { copyToClipboard } from './task-manager-copy';

let app: ReturnType<typeof mount> | null = null;
const SRC = 'run this:\n\n```bash\nls -la\necho hi\n```\n\nthen tell me.';

async function draw(text: string): Promise<HTMLElement> {
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(TaskManagerMarkdown, { target: host, props: { text } });
  flushSync();
  await tick();
  return host;
}

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('command area', () => {
  test('a fenced block draws as a command area with the code, its language and an icon-only copy button', async () => {
    const host = await draw(SRC);
    const box = host.querySelector('[data-task-manager-command]')!;
    expect(box.querySelector('pre code')!.textContent).toBe('ls -la\necho hi');
    expect(box.querySelector('[data-task-manager-command-lang]')!.textContent).toBe('bash');
    const button = box.querySelector<HTMLButtonElement>('[data-task-manager-copy]')!;
    expect(button.getAttribute('aria-label')).toBe('copy');
    expect(button.title).toBe('copy');
    expect(button.textContent!.trim()).toBe('');
    expect(button.querySelector('svg')).not.toBeNull();
  });

  test('a kv fence is not a command area', async () => {
    const host = await draw('```kv\nbranch: main\n```');
    expect(host.querySelector('[data-task-manager-command]')).toBeNull();
    expect(host.querySelector('[data-task-manager-md-kv]')).not.toBeNull();
  });

  test('copy writes the code, shows copied, then returns to copy', async () => {
    vi.useFakeTimers();
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal('navigator', { clipboard: { writeText } });
    const host = await draw(SRC);
    const button = host.querySelector<HTMLButtonElement>('[data-task-manager-copy]')!;
    button.click();
    await vi.advanceTimersByTimeAsync(0);
    flushSync();
    expect(writeText).toHaveBeenCalledWith('ls -la\necho hi');
    expect(button.getAttribute('aria-label')).toBe('copied');
    await vi.advanceTimersByTimeAsync(2000);
    flushSync();
    expect(button.getAttribute('aria-label')).toBe('copy');
  });

  test('a refused copy selects the code for a manual copy and does not claim copied', async () => {
    vi.stubGlobal('navigator', { clipboard: { writeText: vi.fn().mockRejectedValue(new Error('denied')) } });
    const host = await draw(SRC);
    const button = host.querySelector<HTMLButtonElement>('[data-task-manager-copy]')!;
    button.click();
    for (let i = 0; i < 4; i += 1) { await Promise.resolve(); await tick(); }
    expect(button.getAttribute('aria-label')).toBe('copy');
    expect(window.getSelection()!.toString()).toBe('ls -la\necho hi');
  });

  test('copyToClipboard prefers the legacy ladder and reports false with no clipboard at all', async () => {
    vi.stubGlobal('CopyCompat', { copyText: vi.fn().mockResolvedValue({ ok: true }) });
    expect(await copyToClipboard('x')).toBe(true);
    vi.unstubAllGlobals();
    vi.stubGlobal('navigator', {});
    expect(await copyToClipboard('x')).toBe(false);
  });
});

describe('copy of a folded cut', () => {
  test('a block cut by a fold still copies the whole block', async () => {
    const write = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal('navigator', { clipboard: { writeText: write } });
    const host = document.createElement('div');
    document.body.appendChild(host);
    app = mount(TaskManagerMarkdown, { target: host, props: { text: '```\nline one\nline two\nline three\n```', limit: 10, more: true } });
    flushSync();
    await tick();
    expect(host.querySelector('pre code')!.textContent).not.toContain('line three');
    host.querySelector<HTMLButtonElement>('[data-task-manager-copy]')!.click();
    await tick();
    expect(write).toHaveBeenCalledWith('line one\nline two\nline three');
  });
});
