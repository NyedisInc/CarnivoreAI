
import { describe, expect, test } from 'vitest';

import enCatalog from '../../../../client/js/i18n/catalog.en.js';
import { stats } from './stats';

const messages = enCatalog as Record<string, unknown>;

describe('the working-now figure', () => {
  test('the card reads "working now"', () => {
    const card = stats.find((entry) => entry.id === 'running');
    expect(card?.labelKey).toBe('opscenter.stat.running');
    expect(messages['opscenter.stat.running']).toBe('working now');
  });

  test('control: the alive card keeps its own wording', () => {
    expect(messages['opscenter.stat.alive']).toBe('sessions alive');
  });
});
