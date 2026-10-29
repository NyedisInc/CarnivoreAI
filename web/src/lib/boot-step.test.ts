import { afterEach, describe, expect, test, vi } from 'vitest';

import { bootStep } from './boot-step';

afterEach(() => vi.restoreAllMocks());

describe('bootStep', () => {
  test('a throwing step is logged with its name and does not stop the next one', () => {
    const log = vi.spyOn(console, 'error').mockImplementation(() => {});
    const ran: string[] = [];
    bootStep('first', () => {
      throw new Error('boom');
    });
    bootStep('second', () => ran.push('second'));
    expect(ran).toEqual(['second']);
    expect(log).toHaveBeenCalledTimes(1);
    expect(String(log.mock.calls[0]?.[0])).toContain('first');
  });

  test('a rejecting async step is logged by name too', async () => {
    const log = vi.spyOn(console, 'error').mockImplementation(() => {});
    bootStep('later', async () => {
      throw new Error('late boom');
    });
    await Promise.resolve();
    await Promise.resolve();
    expect(String(log.mock.calls[0]?.[0])).toContain('later');
  });
});
