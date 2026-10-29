import { describe, expect, test } from 'vitest';
import { saveLight } from './save-light';

describe('saveLight', () => {
  test('errors are red with a word, unsaved or saving is yellow, clean is green', () => {
    expect(saveLight('loaded', 'failed', true)).toMatchObject({ tone: 'error', wordKey: 'opscenter.cell.notes.word.failed' });
    expect(saveLight('loaded', 'too_large', true)).toMatchObject({ tone: 'error', wordKey: 'opscenter.cell.notes.word.too_large' });
    expect(saveLight('loaded', 'conflict', true)).toMatchObject({ tone: 'error', wordKey: 'opscenter.cell.notes.word.conflict' });
    expect(saveLight('loaded', 'saving', false)).toEqual({ tone: 'pending', labelKey: 'opscenter.cell.notes.saving', wordKey: '' });
    expect(saveLight('loaded', 'idle', true)).toEqual({ tone: 'pending', labelKey: 'opscenter.cell.notes.pending', wordKey: '' });
    expect(saveLight('loaded', 'saved', false)).toEqual({ tone: 'saved', labelKey: 'opscenter.cell.notes.saved', wordKey: '' });
    expect(saveLight('loaded', 'idle', false).tone).toBe('saved');
  });

  test('no loaded note is dim, whatever the save field says', () => {
    for (const load of ['no-session', 'loading', 'failed', 'no-note-row'] as const) {
      expect(saveLight(load, 'failed', true)).toEqual({ tone: 'off', labelKey: 'opscenter.cell.notes.disk_off', wordKey: '' });
    }
  });
});
