/* there is nothing */
import { SAVE_LIGHT_KEYS, type SaveLight } from '../../opscenter/cells/notes/save-light';

export const FILE_CONFLICT_KEY = 'files.editor.disk_conflict';

export interface FileSaveState {
    writable: boolean;
    dirty: boolean;
    saving: boolean;
    stale: boolean;
    failed: boolean;
}

export function fileSaveLight(state: FileSaveState): SaveLight {
    if (!state.writable) return { tone: 'off', labelKey: SAVE_LIGHT_KEYS.off, wordKey: '' };
    if (state.stale) return { tone: 'error', labelKey: FILE_CONFLICT_KEY, wordKey: 'opscenter.cell.notes.word.conflict' };
    if (state.failed) return { tone: 'error', labelKey: SAVE_LIGHT_KEYS.failed, wordKey: 'opscenter.cell.notes.word.failed' };
    if (state.saving) return { tone: 'pending', labelKey: SAVE_LIGHT_KEYS.saving, wordKey: '' };
    if (state.dirty) return { tone: 'pending', labelKey: SAVE_LIGHT_KEYS.pending, wordKey: '' };
    return { tone: 'saved', labelKey: SAVE_LIGHT_KEYS.saved, wordKey: '' };
}
