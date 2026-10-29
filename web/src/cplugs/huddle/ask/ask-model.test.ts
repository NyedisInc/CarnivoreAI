import { describe, expect, test } from 'vitest';
import {
  answerWords, answeredByComment, drawnQuestions, hasRecommendation, hiddenSkips, inlineQuestion, isAnswered, moveInOrder, optionForDigit, payloadOf, progress, recommendable, startingOrder,
  takeAll, takeRecommendation, toggleChoice, tookRecommendation, type AskQuestion,
} from './ask-model';

const yn: AskQuestion = { id: 'a', type: 'yes_no', prompt: 'close?', required: true, labels: ['close', 'keep'], recommend: { value: true, reason: 'r' } };
const single: AskQuestion = { id: 'b', type: 'single', prompt: 'which?', required: true, other: true, options: [
  { id: 'x', label: 'X', recommended: true, reason: 'why' }, { id: 'y', label: 'Y' }] };
const multi: AskQuestion = { id: 'c', type: 'multi', prompt: 'any?', required: false, max: 2, options: [
  { id: 'p', label: 'P', recommended: true }, { id: 'q', label: 'Q' }, { id: 'r', label: 'R', recommended: true }] };
const rank: AskQuestion = { id: 'd', type: 'rank', prompt: 'order', required: true, options: [{ id: 'm', label: 'M' }, { id: 'n', label: 'N' }], recommend: { order: ['n', 'm'] } };
const text: AskQuestion = { id: 'e', type: 'long_text', prompt: 'say', required: false, recommend: { text: 'suggested' } };
const all = [yn, single, multi, rank, text];

describe('isAnswered', () => {
  test('each type needs its own answer, and a rank only counts once touched', () => {
    expect(isAnswered(yn, { value: false })).toBe(true);
    expect(isAnswered(yn, {})).toBe(false);
    expect(isAnswered(single, { choice: 'x' })).toBe(true);
    expect(isAnswered(single, { other: '  ' })).toBe(false);
    expect(isAnswered(single, { choice: null, other: 'z' })).toBe(true);
    expect(isAnswered(multi, { choices: [] })).toBe(false);
    expect(isAnswered(rank, { order: ['m', 'n'] })).toBe(false);
    expect(isAnswered(rank, { order: ['m', 'n'], touched: true })).toBe(true);
    expect(isAnswered(text, { text: ' ' })).toBe(false);
    expect(isAnswered(text, undefined)).toBe(false);
  });
});

describe('progress and recommendations', () => {
  test('counts the done and the required left; a recommendation never pre-answers', () => {
    expect(progress(all, {})).toEqual({ total: 5, done: 0, requiredLeft: 3 });
    expect(progress(all, { a: { value: true }, c: { choices: ['q'] } })).toEqual({ total: 5, done: 2, requiredLeft: 2 });
  });
  test('take recommendation fills each type in its answer shape', () => {
    expect(takeRecommendation(yn)).toEqual({ value: true });
    expect(takeRecommendation(single)).toEqual({ choice: 'x' });
    expect(takeRecommendation(multi)).toEqual({ choices: ['p', 'r'] });
    expect(takeRecommendation(rank)).toEqual({ order: ['n', 'm'], touched: true });
    expect(takeRecommendation(text)).toEqual({ text: 'suggested' });
    expect(takeRecommendation({ ...yn, recommend: undefined })).toBeNull();
    expect(hasRecommendation(single)).toBe(true);
    expect(hasRecommendation({ ...single, options: [{ id: 'x', label: 'X' }, { id: 'y', label: 'Y' }] })).toBe(false);
  });
  test('take all fills only the unanswered, keeps the answered and the notes', () => {
    const out = takeAll(all, { a: { value: false, note: 'n' }, b: { note: 'later' } });
    expect(out.a).toEqual({ value: false, note: 'n' });
    expect(out.b).toEqual({ note: 'later', choice: 'x' });
    expect(out.d?.touched).toBe(true);
    expect(recommendable(all, { a: { value: true } })).toBe(4);
  });
  test('tookRecommendation compares with the recommendation; null when there is none', () => {
    expect(tookRecommendation(yn, { value: true })).toBe(true);
    expect(tookRecommendation(yn, { value: false })).toBe(false);
    expect(tookRecommendation(rank, { order: ['n', 'm'] })).toBe(true);
    expect(tookRecommendation({ ...yn, recommend: undefined }, { value: true })).toBeNull();
  });
});

describe('ordering and picks', () => {
  test('a rank starts at the recommended order, moves stay in range, and a digit names the nth option', () => {
    expect(startingOrder(rank)).toEqual(['n', 'm']);
    expect(startingOrder({ ...rank, recommend: undefined })).toEqual(['m', 'n']);
    expect(moveInOrder(['a', 'b', 'c'], 'c', -1)).toEqual(['a', 'c', 'b']);
    expect(moveInOrder(['a', 'b', 'c'], 'a', -1)).toEqual(['a', 'b', 'c']);
    expect(moveInOrder(['a', 'b', 'c'], 'c', 1)).toEqual(['a', 'b', 'c']);
    expect(optionForDigit(single, '2')).toBe('y');
    expect(optionForDigit(single, '9')).toBeNull();
    expect(optionForDigit(single, 'a')).toBeNull();
  });
  test('a multi toggles and never passes its max', () => {
    expect(toggleChoice(multi, { choices: ['p'] }, 'q').choices).toEqual(['p', 'q']);
    expect(toggleChoice(multi, { choices: ['p', 'q'] }, 'r').choices).toEqual(['p', 'q']);
    expect(toggleChoice(multi, { choices: ['p', 'q'] }, 'p').choices).toEqual(['q']);
  });
});

describe('payloadOf and answerWords', () => {
  test('only answered questions ride, in the shapes the server takes, with notes', () => {
    const payload = payloadOf(all, {
      a: { value: true, note: ' but later ' }, b: { choice: null, other: ' z ' }, c: { choices: ['q'] },
      d: { order: ['m', 'n'] }, e: { note: 'only a note' },
    });
    expect(payload).toEqual({ a: { value: true, note: 'but later' }, b: { choice: null, other: 'z' }, c: { choices: ['q'] }, e: { note: 'only a note' } });
  });
  test('a stored answer reads back in words', () => {
    const tr = (key: string): string => ({ 'cplug.huddle.ask.other': 'autre', 'cplug.huddle.ask.dismissed': 'ecarte' }[key] ?? key);
    expect(answerWords({ order: ['n', 'm'], labels: ['N', 'M'] }, tr)).toBe('N > M');
    expect(answerWords({ labels: ['P', 'R'], other: 'z' }, tr)).toBe('P, R, autre: z');
    expect(answerWords({ label: 'close' }, tr)).toBe('close');
    expect(answerWords({ skipped: true }, tr)).toBe('');
    expect(answerWords({ skipped: true, dismissed: true }, tr)).toBe('ecarte');
    expect(answerWords(undefined, tr)).toBe('');
  });
});

describe('answeredByComment', () => {
  test('only a freeform reply to that question counts, never a form submit', () => {
    expect(answeredByComment([{ answers_to: 5, freeform: true }], 5)).toBe(true);
    expect(answeredByComment([{ answers_to: 5 }], 5)).toBe(false);
    expect(answeredByComment([{ answers_to: 6, freeform: true }], 5)).toBe(false);
    expect(answeredByComment([], 5)).toBe(false);
  });
});

describe('a command question stands alone (#1797)', () => {
  const opts = [{ id: 'ran', label: 'ran it' }, { id: 'failed', label: 'failed' }];
  const handoff: AskQuestion = { id: 'ho', type: 'single', prompt: 'Run it', required: true, options: opts, command: { text: 'ls' } };
  const plain: AskQuestion = { id: 'why', type: 'long_text', prompt: 'why?', required: true };

  test('drawnQuestions keeps only the command question of a mixed form and leaves other forms whole', () => {
    expect(drawnQuestions([plain, handoff])).toEqual([handoff]);
    expect(drawnQuestions([plain, plain])).toHaveLength(2);
    expect(drawnQuestions([handoff])).toEqual([handoff]);
  });

  test('hiddenSkips skips the questions that are not drawn, and a mixed form answers inline as the command question', () => {
    expect(hiddenSkips([plain, handoff], [handoff])).toEqual({ why: { skipped: true } });
    expect(inlineQuestion([plain, handoff])).toBe(handoff);
  });
});
