/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import { bubbleKindOf, isFormAnswer } from './task-manager-bubbles';
import { t } from '../sdk';
import { formAnswerRows } from './task-manager-form-answer';
import HuddleThread from './HuddleThread.svelte';

const base = { item_id: 1, answered: false, created_at: 5, seq: 5 };
const typed = { ...base, id: 7, author: 'joe', kind: 'reply', text: 'answers to 2 questions: 1. ship? yes' };
const formAnswer = {
  ...base, id: 8, author: 'joe', kind: 'reply', text: 'answers to 2 questions: 1. ship? yes 2. when? skipped', answers_to: 6,
  answers: { a: { value: true, label: 'yes', prompt: 'ship?', note: 'after lunch' }, b: { skipped: true, prompt: 'when?' } },
};
const item = { id: 1, list: 'all', kind: '', created_by: 'joe', status: 'working', text: 't', created_seq: 0, thread: [typed, formAnswer] } as never;

let app: ReturnType<typeof mount> | null = null;
afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

describe('form answers are detected by structure', () => {
  test('answers + answers_to make a form answer; a plain Joe message and Claude are untouched', () => {
    expect(isFormAnswer(formAnswer as never)).toBe(true);
    expect(bubbleKindOf(formAnswer as never)).toBe('form_answer');
    expect(bubbleKindOf(typed as never)).toBe('owner');
    expect(bubbleKindOf({ author: 'claude', kind: 'info' })).toBe('info');
    expect(bubbleKindOf({ author: 'joe', kind: 'reply', text: 'answers to 1 questions: 1. x? y' } as never)).toBe('owner');
  });

  test('rows pair prompt and answer, and a skip stays a skip', () => {
    const rows = formAnswerRows(formAnswer as never, t);
    expect(rows.map((r) => [r.prompt, r.words, r.state, r.note])).toEqual([['ship?', 'yes', 'answered', 'after lunch'], ['when?', '', 'skipped', '']]);
  });
});

describe('the thread draws the answer card', () => {
  test('a form answer is the card with its icon and the list; a typed message is not', () => {
    const host = document.createElement('div');
    document.body.append(host);
    app = mount(HuddleThread, { target: host, props: { item, closed: true } });
    flushSync();
    const card = host.querySelector('[data-task-manager-message="8"]') as HTMLElement;
    expect(card.dataset.hb).toBe('form_answer');
    expect(card.classList.contains('hdt-msg--form')).toBe(true);
    expect(card.querySelector('.hb-fa-icon svg')).not.toBeNull();
    const rows = [...card.querySelectorAll('[data-task-manager-form-answer]')] as HTMLElement[];
    expect(rows.map((r) => r.querySelector('.hdfa-prompt')?.textContent)).toEqual(['ship?', 'when?']);
    expect(rows[0].querySelector('.hdfa-words')?.textContent).toBe('yes');
    expect(rows[0].querySelector('.hdfa-note')?.textContent).toBe('after lunch');
    expect(rows[1].dataset.state).toBe('skipped');
    expect(rows[1].querySelector('.hdfa-words')?.textContent).toMatch(/skipped/);
    const plain = host.querySelector('[data-task-manager-message="7"]') as HTMLElement;
    expect(plain.dataset.hb).toBe('owner');
    expect(plain.querySelector('[data-task-manager-form-answers]')).toBeNull();
    expect(plain.classList.contains('hdt-msg--joe')).toBe(true);
  });
});
