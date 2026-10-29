/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import HuddleReview from './HuddleReview.svelte';
import { reviewAnswerOf, reviewOf, summarize } from './huddle-review';
import { reviewOpen, setReviewOpen } from './task-manager-review-fold';

vi.mock('./huddle.svelte', () => ({ readPost: vi.fn(), reply: vi.fn() }));

let app: ReturnType<typeof mount> | null = null;
const settle = async (): Promise<void> => { await tick(); flushSync(); };
beforeEach(() => { window.localStorage.clear(); });
afterEach(() => { if (app) unmount(app); app = null; document.body.innerHTML = ''; });

async function draw(props: Record<string, unknown>): Promise<HTMLElement> {
  const host = document.createElement('div');
  document.body.appendChild(host);
  app = mount(HuddleReview as never, { target: host, props });
  await settle();
  return host;
}

const LONG = '**What changed:** the card now folds. It also does more.\n- bullet one\n- bullet two';
const item = (extra: Record<string, unknown>) => ({ id: 9, status: 'review', thread: [], ...extra }) as never;
const m = (id: number, author: string, kind: string, extra: Record<string, unknown> = {}) =>
  ({ id, item_id: 9, author, kind, text: `t${id}`, answered: false, created_at: id, seq: id, ...extra });

describe('summarize', () => {
  test('first sentence of the first line, markdown stripped', () => {
    expect(summarize(LONG)).toEqual({ summary: 'What changed: the card now folds.', more: true });
  });
  test('a list or heading first line loses its marker; one short line has nothing more', () => {
    expect(summarize('- did the thing').summary).toBe('did the thing');
    expect(summarize('# Done\nmore')).toEqual({ summary: 'Done', more: true });
    expect(summarize('fixed the bell')).toEqual({ summary: 'fixed the bell', more: false });
    expect(summarize('')).toEqual({ summary: '', more: false });
  });
  test('a long sentence is cut and offers the rest', () => {
    const out = summarize('x'.repeat(300));
    expect(out.summary.length).toBe(140);
    expect(out.more).toBe(true);
  });
});

describe('reviewOf', () => {
  test('derives the summary when no stored field exists', () => {
    const block = reviewOf(item({ review_description: LONG, review_where: 'huddle tab' }));
    expect(block?.summary).toBe('What changed: the card now folds.');
    expect(block?.hasMore).toBe(true);
  });
});

describe('a stored review_summary', () => {
  test('wins over the derived first sentence and keeps the description in the fold', () => {
    const block = reviewOf(item({ review_summary: 'card reworked', review_description: LONG }))!;
    expect(block.summary).toBe('card reworked');
    expect(block.hasMore).toBe(true);
    expect(reviewOf(item({ review_summary: 'same', review_description: 'same' }))!.hasMore).toBe(false);
  });
});

describe('the card', () => {
  const block = reviewOf(item({ review_description: LONG, review_where: 'huddle tab', review_link: '/#/huddle' }))!;

  test('description is folded by default; the summary and the review part show; review is last', async () => {
    const host = await draw({ id: 9, block });
    const card = host.querySelector('[data-task-manager-review="9"]')!;
    expect(card.querySelector('[data-task-manager-review-summary]')!.textContent).toContain('What changed: the card now folds.');
    expect(card.querySelector('[data-task-manager-review-description]')).toBeNull();
    const part = card.querySelector('[data-task-manager-review-part]')!;
    expect(part.querySelector('[data-task-manager-review-where]')!.textContent).toBe('huddle tab');
    expect(part.querySelector('[data-task-manager-review-link]')).not.toBeNull();
    expect(part.querySelector('[data-task-manager-action]')!.getAttribute('data-task-manager-action')).toBe('tick');
    expect(part.nextElementSibling).toBeNull();
  });

  test('unfolding shows the description between summary and review part and is remembered per item', async () => {
    const host = await draw({ id: 9, block });
    host.querySelector<HTMLButtonElement>('[data-task-manager-review-fold]')!.click();
    await settle();
    const text = host.querySelector('[data-task-manager-review-description]')!;
    expect(text.previousElementSibling).toBe(host.querySelector('[data-task-manager-review-summary]'));
    expect(text.nextElementSibling).toBe(host.querySelector('[data-task-manager-review-part]'));
    expect(reviewOpen(9)).toBe(true);
    expect(reviewOpen(10)).toBe(false);
    unmount(app!); app = null; document.body.innerHTML = '';
    const again = await draw({ id: 9, block });
    expect(again.querySelector('[data-task-manager-review-description]')).not.toBeNull();
  });

  test('clicking a code block\'s copy key copies and leaves the description open', async () => {
    const code = reviewOf(item({ review_description: 'run this\n\n```bash\nls -la\n```\n\nthen tell me.' }))!;
    setReviewOpen(9, true);
    const write = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal('navigator', { clipboard: { writeText: write } });
    const host = await draw({ id: 9, block: code });
    host.querySelector<HTMLButtonElement>('[data-task-manager-copy]')!.click();
    await settle();
    expect(write).toHaveBeenCalledWith('ls -la');
    expect(reviewOpen(9)).toBe(true);
    expect(host.querySelector('[data-task-manager-review-description]')).not.toBeNull();
    vi.unstubAllGlobals();
  });

  test('the link reads github issue #N when it is the item\'s own issue, else open link', async () => {
    const url = 'https://github.com/NyedisInc/CarnivoreAI/issues/1746';
    const withIssue = reviewOf(item({ review_description: 'x', review_link: url }))!;
    const same = await draw({ id: 9, block: withIssue, issue: url });
    expect(same.querySelector('[data-task-manager-review-link]')!.textContent).toBe('github issue #1746');
    unmount(app!); app = null; document.body.innerHTML = '';
    const other = await draw({ id: 9, block: withIssue, issue: 'https://github.com/NyedisInc/CarnivoreAI/issues/5' });
    expect(other.querySelector('[data-task-manager-review-link]')!.textContent).toBe('open link');
  });

  test('a one-line description has no fold key', async () => {
    const one = reviewOf(item({ review_description: 'fixed the bell' }))!;
    const host = await draw({ id: 9, block: one });
    expect(host.querySelector('[data-task-manager-review-fold]')).toBeNull();
  });

  test('blocked storage reads as folded and never throws', () => {
    const spy = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked'); });
    const set = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked'); });
    expect(reviewOpen(1)).toBe(false);
    expect(() => setReviewOpen(1, true)).not.toThrow();
    spy.mockRestore(); set.mockRestore();
  });
});

describe('the answer line', () => {
  const asked = [m(1, 'joe', 'reply'), m(2, 'claude', 'answer', { quote: { id: 1, text: 'q' }, text: 'Yes, it does. Because of x.\nSecond line.' })];

  test('is the newest agent answer quoting a plain reply of the owner', () => {
    const later = [...asked, m(3, 'joe', 'reply'), m(4, 'claude', 'answer', { quote: { id: 3, text: 'q' }, text: 'ok' })];
    expect(reviewAnswerOf(item({ thread: later }))?.id).toBe(4);
    expect(reviewAnswerOf(item({ thread: asked }))).toMatchObject({ id: 2, summary: 'Yes, it does.', hasMore: true });
  });

  test('none when unanswered, when the answer quotes something that is not their plain reply, or on a form answer', () => {
    expect(reviewAnswerOf(item({ thread: [m(1, 'joe', 'reply')] }))).toBeNull();
    expect(reviewAnswerOf(item({ thread: [m(1, 'joe', 'reply', { answers_to: 0, freeform: true }), m(2, 'claude', 'answer', { quote: { id: 1, text: 'q' } })] }))).toBeNull();
    expect(reviewAnswerOf(item({ thread: [m(2, 'claude', 'answer', { quote: { id: null, text: 'q' } })] }))).toBeNull();
  });

  test('draws below the card as the last line, compact, the rest behind more', async () => {
    const block = reviewOf(item({ review_description: 'fixed' }))!;
    const host = await draw({ id: 9, block, answer: reviewAnswerOf(item({ thread: asked })) });
    const wrap = host.querySelector('[data-task-manager-review-wrap="9"]')!;
    const line = wrap.querySelector('[data-task-manager-review-answer]')!;
    expect(wrap.lastElementChild).toBe(line);
    expect(line.previousElementSibling).toBe(wrap.querySelector('[data-task-manager-review="9"]'));
    expect(line.textContent).toContain('Yes, it does.');
    expect(line.textContent).not.toContain('Second line');
    line.querySelector<HTMLButtonElement>('[data-task-manager-review-answer-more]')!.click();
    await settle();
    expect(line.textContent).toContain('Second line');
  });
});

describe('click anywhere on the description section (#1668)', () => {
  const block = () => reviewOf(item({ review_description: '**Done:** a thing. [docs](https://x.test)\n- more', review_where: 'tab' }))!;
  const sum = (h: HTMLElement) => h.querySelector('[data-task-manager-review-summary]') as HTMLElement;

  test('a click on the summary text toggles it open and closed', async () => {
    const h = await draw({ block: block(), id: 9 });
    expect(h.querySelector('[data-task-manager-review-description]')).toBeNull();
    (h.querySelector('.tkm-review-line') as HTMLElement).click(); await settle();
    expect(h.querySelector('[data-task-manager-review-description]')).not.toBeNull();
    (h.querySelector('[data-task-manager-review-description]') as HTMLElement).click(); await settle();
    expect(h.querySelector('[data-task-manager-review-description]')).toBeNull();
  });
  test('a link click inside the opened description does not toggle; a selection does not either', async () => {
    const h = await draw({ block: block(), id: 9 });
    sum(h).click(); await settle();
    const a = h.querySelector('[data-task-manager-review-description] a') as HTMLElement;
    a.addEventListener('click', (e) => e.preventDefault());
    a.click(); await settle();
    expect(h.querySelector('[data-task-manager-review-description]')).not.toBeNull();
    const sel = vi.spyOn(window, 'getSelection').mockReturnValue({ toString: () => 'Done' } as never);
    (h.querySelector('[data-task-manager-review-description]') as HTMLElement).click(); await settle();
    expect(h.querySelector('[data-task-manager-review-description]')).not.toBeNull();
    sel.mockRestore();
  });
  test('the fold button stays a focusable button and its click toggles exactly once', async () => {
    const h = await draw({ block: block(), id: 9 });
    const btn = h.querySelector('[data-task-manager-review-fold]') as HTMLButtonElement;
    expect(btn.tagName).toBe('BUTTON');
    btn.click(); await settle();
    expect(h.querySelector('[data-task-manager-review-description]')).not.toBeNull();
    expect(reviewOpen(9)).toBe(true);
  });
  test('hover text: the folded section carries the plain full description, gone once open', async () => {
    const h = await draw({ block: block(), id: 9 });
    const tip = sum(h).getAttribute('data-tooltip');
    expect(tip).toContain('Done: a thing.');
    expect(tip).toContain('more');
    expect(tip).not.toMatch(/\*\*|\]\(/);
    sum(h).click(); await settle();
    expect(sum(h).hasAttribute('data-tooltip')).toBe(false);
  });
  test('a one-line description has no click target and no tip', async () => {
    const h = await draw({ block: reviewOf(item({ review_description: 'fixed it' }))!, id: 9 });
    expect(sum(h).hasAttribute('data-tooltip')).toBe(false);
    sum(h).click(); await settle();
    expect(h.querySelector('[data-task-manager-review-description]')).toBeNull();
  });
});
