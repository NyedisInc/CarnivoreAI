/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const PROMPT = 'until when? (only for give it until)';
const ASK = {
  item: 1, message: 10, typed: true, answered: false, answer_message_id: null,
  ask: { context: '', questions: [{ id: 'q2', type: 'datetime', prompt: PROMPT, required: false }] },
};
const server = vi.hoisted(() => ({ refuse: true }));

vi.mock('../../../opscenter/api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../../opscenter/api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string) => {
      if (path === '/cplugs/huddle/questions/10') return ASK;
      if (path === '/cplugs/huddle/questions/10/answer') {
        if (!server.refuse) return { item: {}, message: { id: 11 } };
        const detail = { code: 'task_manager_invalid', detail: 'question q2: the time must be ISO 8601 with a UTC offset', question: { id: 'q2', rule: 'time', item: 1 } };
        throw new real.ApiError(detail.detail, 400, null, { detail });
      }
      if (path === '/cplugs/huddle/send') return { results: [{ list: 'all', status: 'sent' }] };
      if (path === '/cplugs/huddle') return { revision: 1, settings: { hideCompleted: false, view: 'status', density: 'normal' } };
      if (path === '/cplugs/huddle/focus') return { focus: null };
      if (path === '/cplugs/huddle/lists') return { cursor: 0, lists: [] };
      return {};
    },
  };
});

import { t } from '../../sdk';
import { huddle } from '../huddle.svelte';
import { cplugEnablement } from '../../host/enablement.svelte';
import TaskManagerAskForm from './TaskManagerAskForm.svelte';
import { refusalSentence } from './ask-refusal';
import { answerRefusalShown, clearAnswerRefusal, clearAnswerRefusalFor, settleAnswerRefusal, showAnswerRefusal } from './ask-notice.svelte';

cplugEnablement.enabled = { huddle: true };
let app: ReturnType<typeof mount> | null = null;

/** Let the read, the mount and the submit's queued save run. */
async function settle(): Promise<void> {
  for (let i = 0; i < 12; i += 1) { await Promise.resolve(); await tick(); }
  flushSync();
}

function onScreen(): void {
  huddle.groups = null;
  huddle.selected = 'all';
  huddle.body = { list: 'all', items: [{ id: 1, list: 'all', text: 'x', title: 'restart staging', state: 'waiting',
    thread: [{ id: 10, item_id: 1, author: 'claude', kind: 'question', text: 'what now?', answered: false, created_at: 0, seq: 1 }] }] } as never;
}

async function submitOnce(): Promise<HTMLElement> {
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(TaskManagerAskForm, { target: host, props: { messageId: 10, mode: 'panel', onClose: vi.fn() } });
  await settle();
  const field = host.querySelector('[data-ask-field="q2"]') as HTMLInputElement;
  field.value = '2030-11-03T09:30';
  field.dispatchEvent(new Event('input', { bubbles: true }));
  await settle();
  (host.querySelector('[data-ask-submit]') as HTMLElement).click(); // safe: an unanswered form always draws its submit key
  await settle();
  return host;
}

beforeEach(() => {
  server.refuse = true;
  clearAnswerRefusal();
  huddle.notice = '';
  onScreen();
});
afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

describe('the refusal sentence', () => {
  test('names the task and the box by its label in the catalog words', () => {
    const text = refusalSentence(t, { id: 'q2', rule: 'time', item: 1 }, { title: 'restart staging', questions: [{ id: 'q2', prompt: PROMPT }], reason: '' });
    expect(text).toBe(`restart staging: "${PROMPT}" needs a date and time from the picker`);
  });
  test('an untitled task leads with the box, never with an empty name', () => {
    const text = refusalSentence(t, { id: 'q2', rule: 'time', item: 1 }, { title: '  ', questions: [{ id: 'q2', prompt: PROMPT }], reason: '' });
    expect(text).toBe(`"${PROMPT}" needs a date and time from the picker`);
  });
  test('a rule the catalog does not know reads as refused with the reason, without the id head', () => {
    const text = refusalSentence(t, { id: 'q2', rule: 'brand_new', item: 1 },
      { title: 'restart staging', questions: [{ id: 'q2', prompt: PROMPT }], reason: 'question q2: time is over 40 characters' });
    expect(text).toBe(`restart staging: "${PROMPT}" was refused: time is over 40 characters`);
  });
});

describe('the notice line after a refused answer', () => {
  test('names the task and the box, never the bare id', async () => {
    await submitOnce();
    expect(huddle.notice).toBe(`restart staging: "${PROMPT}" needs a date and time from the picker`);
    expect(huddle.notice).not.toContain('q2');
    expect(answerRefusalShown()).toBe(true);
  });

  test('clears when a later save of the answer lands', async () => {
    await submitOnce();
    expect(answerRefusalShown()).toBe(true);
    server.refuse = false;
    if (app) unmount(app);
    app = null;
    await submitOnce();
    expect(huddle.notice).toBe('');
  });

  test('clears once its question reads answered', () => {
    showAnswerRefusal(10, 1, 'refused words');
    settleAnswerRefusal();
    expect(huddle.notice).toBe('refused words');
    (huddle.body?.items[0]?.thread[0] as { answered: boolean }).answered = true;
    settleAnswerRefusal();
    expect(huddle.notice).toBe('');
  });

  test('clears once its task is gone from the list it showed on', () => {
    showAnswerRefusal(10, 1, 'refused words');
    huddle.body = { list: 'all', items: [{ id: 2, list: 'all', text: 'y', title: '', thread: [] }] } as never;
    settleAnswerRefusal();
    expect(huddle.notice).toBe('');
  });

  test('stays while another list is on screen or the list is still loading, and clears once its own list lacks the task', () => {
    showAnswerRefusal(10, 1, 'refused words');
    huddle.selected = 'proj';
    huddle.body = { list: 'proj', items: [{ id: 2, list: 'proj', text: 'y', title: '', thread: [] }] } as never; // `as never`: a minimal row
    settleAnswerRefusal();
    expect(huddle.notice).toBe('refused words');
    huddle.selected = 'all';
    huddle.body = null;
    settleAnswerRefusal();
    expect(huddle.notice).toBe('refused words');
    huddle.body = { list: 'all', items: [] } as never;
    settleAnswerRefusal();
    expect(huddle.notice).toBe('');
  });

  test("a save of another question leaves this question's refusal; its own save clears it", () => {
    showAnswerRefusal(10, 1, 'refused words');
    clearAnswerRefusalFor(99);
    expect(huddle.notice).toBe('refused words');
    clearAnswerRefusalFor(10);
    expect(huddle.notice).toBe('');
  });

  test('the dismiss clears it, and another writer\'s words are never touched', () => {
    showAnswerRefusal(10, 1, 'refused words');
    clearAnswerRefusal();
    expect(huddle.notice).toBe('');
    showAnswerRefusal(10, 1, 'refused words');
    huddle.notice = 'something else';
    clearAnswerRefusal();
    expect(huddle.notice).toBe('something else');
  });
});
