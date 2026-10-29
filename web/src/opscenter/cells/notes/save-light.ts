import type { LoadState, SaveState } from '../../api/notes.svelte';

export type SaveTone = 'error' | 'pending' | 'saved' | 'off';

export interface SaveLight {
  tone: SaveTone;
  labelKey: string;
  wordKey: string;
}

export const SAVE_LIGHT_KEYS = {
  saving: 'opscenter.cell.notes.saving',
  pending: 'opscenter.cell.notes.pending',
  saved: 'opscenter.cell.notes.saved',
  failed: 'opscenter.cell.notes.failed',
  tooLarge: 'opscenter.cell.notes.too_large',
  conflict: 'opscenter.cell.notes.disk_conflict',
  off: 'opscenter.cell.notes.disk_off',
} as const;

const ERROR_WORDS = {
  failed: 'opscenter.cell.notes.word.failed',
  too_large: 'opscenter.cell.notes.word.too_large',
  conflict: 'opscenter.cell.notes.word.conflict',
} as const;

const ERROR_LABELS = {
  failed: SAVE_LIGHT_KEYS.failed,
  too_large: SAVE_LIGHT_KEYS.tooLarge,
  conflict: SAVE_LIGHT_KEYS.conflict,
} as const;

export function saveLight(load: LoadState, save: SaveState, dirty: boolean): SaveLight {
  if (load !== 'loaded') return { tone: 'off', labelKey: SAVE_LIGHT_KEYS.off, wordKey: '' };
  if (save === 'failed' || save === 'too_large' || save === 'conflict') {
    return { tone: 'error', labelKey: ERROR_LABELS[save], wordKey: ERROR_WORDS[save] };
  }
  if (save === 'saving') return { tone: 'pending', labelKey: SAVE_LIGHT_KEYS.saving, wordKey: '' };
  if (dirty) return { tone: 'pending', labelKey: SAVE_LIGHT_KEYS.pending, wordKey: '' };
  return { tone: 'saved', labelKey: SAVE_LIGHT_KEYS.saved, wordKey: '' };
}
