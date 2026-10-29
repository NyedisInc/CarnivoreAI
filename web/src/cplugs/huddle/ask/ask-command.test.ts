/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import AskQuestion from './AskQuestion.svelte';
import type { AskQuestion as Question } from './ask-model';

let app: ReturnType<typeof mount> | null = null;
const OPTIONS = [{ id: 'ran', label: 'ran it' }, { id: 'failed', label: 'failed' }, { id: 'skip', label: 'skip' }];
const WITH: Question = { id: 'ho', type: 'single', prompt: 'Run the handoff', required: true, options: OPTIONS, command: { text: '~/.handoff/handoff x', lang: 'bash' } };

async function draw(question: Question, onChange = vi.fn()): Promise<HTMLElement> {
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(AskQuestion, { target: host, props: { question, number: 1, value: undefined, onChange, onTake: vi.fn() } });
  flushSync();
  await tick();
  return host;
}

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

describe('question command and pills', () => {
  test('the command area is above the pills and the pills carry no number or mark', async () => {
    const host = await draw(WITH);
    const command = host.querySelector('[data-ask-command="ho"]')!;
    const pills = host.querySelector('.hdq-pills')!;
    expect(command.textContent).toContain('~/.handoff/handoff x');
    expect(command.compareDocumentPosition(pills) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const rows = [...pills.querySelectorAll<HTMLElement>('[data-ask-option]')];
    expect(rows.map((r) => r.textContent!.trim())).toEqual(['ran it', 'failed', 'skip']);
    expect(rows.every((r) => r.hasAttribute('data-btn') && !r.className && !r.querySelector('.hdq-mark'))).toBe(true);
  });

  test('one tap on a pill answers with the unchanged single shape', async () => {
    const onChange = vi.fn();
    const host = await draw(WITH, onChange);
    host.querySelector<HTMLElement>('[data-ask-option="failed"]')!.click();
    expect(onChange).toHaveBeenCalledWith({ choice: 'failed', other: '' });
  });

  test('a single without a command keeps its numbered radio rows and shows no command area', async () => {
    const host = await draw({ ...WITH, command: undefined });
    expect(host.querySelector('[data-ask-command]')).toBeNull();
    expect(host.querySelector('.hdq-pills')).toBeNull();
    expect(host.querySelector('[data-ask-option="ran"]')!.textContent).toMatch(/1\.\s*ran it/);
  });
});
