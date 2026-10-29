import { describe, expect, test } from 'vitest';
import { waitingToSend } from './huddle-send-many.svelte';
import { t } from '../sdk';
import { AGGREGATE } from './huddle-model';

const rows = [{ key: 'all', waiting_to_send: 1 }, { key: '12', waiting_to_send: 2 }, { key: '18' }];

describe('waitingToSend', () => {
  test('all projects sums every list; an older server row counts zero', () => {
    expect(waitingToSend(AGGREGATE, rows)).toBe(3);
  });
  test('one list counts only itself; none waiting is zero (key disabled)', () => {
    expect(waitingToSend('12', rows)).toBe(2);
    expect(waitingToSend('18', rows)).toBe(0);
  });
});

describe('the send key words', () => {
  test('say send to carnivore with the count, or that nothing waits', () => {
    expect(t('cplug.huddle.send.button')).toBe('send to carnivore');
    expect(t('cplug.huddle.send.waiting', { count: 3 })).toBe('send to carnivore: 3 changes waiting');
    expect(t('cplug.huddle.send.waiting', { count: 1 })).toBe('send to carnivore: 1 change waiting');
    expect(t('cplug.huddle.send.nothing')).toBe('nothing waiting to send');
  });
});
