import { findItem, huddle } from '../huddle.svelte';

const shown = $state<{ question: number | null; item: number | null; list: string; text: string }>({ question: null, item: null, list: '', text: '' });

export function showAnswerRefusal(question: number, item: number | null, text: string): void {
  huddle.notice = text;
  shown.question = question;
  shown.item = item;
  shown.list = huddle.selected;
  shown.text = text;
}

export function answerRefusalShown(): boolean {
  return shown.question !== null && huddle.notice === shown.text;
}

export function clearAnswerRefusal(): void {
  if (answerRefusalShown()) huddle.notice = '';
  shown.question = null;
  shown.item = null;
  shown.list = '';
  shown.text = '';
}

export function clearAnswerRefusalFor(question: number): void {
  if (shown.question === question) clearAnswerRefusal();
}

export function answerRefusalSettled(): boolean {
  if (!answerRefusalShown() || shown.item === null) return false;
  const item = findItem(shown.item);
  if (!item) return huddle.selected === shown.list && (huddle.groups !== null || huddle.body !== null);
  return item.thread.some((m) => m.id === shown.question && m.answered);
}

export function settleAnswerRefusal(): void {
  if (answerRefusalSettled()) clearAnswerRefusal();
}
