import { describe, expect, test } from 'vitest';
import askFormSource from './TaskManagerAskForm.svelte?raw';

describe('answer heading hover', () => {
  test('the form uses the shared truncatedTip on its name', () => {
    expect(askFormSource).toMatch(/class="hdq-name"[^>]*use:truncatedTip=\{mdPlain\(name\)\}/);
  });
});
