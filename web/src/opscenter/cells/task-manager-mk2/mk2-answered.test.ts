import { describe, expect, test } from 'vitest';
import type { Message } from '../../../cplugs/huddle/task-manager-design/model';
import { answeredOf } from './mk2-answered';

const ask = (answered: boolean): Message => ({ by: 'agent', kind: 'question', time: '1:00 pm', text: 'q', answered });
const reply = (time: string): Message => ({ by: 'you', time, text: 'a' });

describe('answeredOf', () => {
  test('a task that never asked has no field', () => {
    expect(answeredOf([{ by: 'agent', time: '1:00 pm', text: 'done' }])).toBeNull();
  });
  test('an open question reads no', () => {
    expect(answeredOf([ask(true), reply('2:00 pm'), ask(false)])).toEqual({ answered: false, time: null });
  });
  test('every question answered reads yes with the time of the owner reply after the newest one', () => {
    expect(answeredOf([ask(true), reply('2:00 pm'), ask(true), reply('3:30 pm')])).toEqual({ answered: true, time: '3:30 pm' });
  });
  test('an answer given in the terminal has no time', () => {
    expect(answeredOf([ask(true)])).toEqual({ answered: true, time: null });
  });
});
