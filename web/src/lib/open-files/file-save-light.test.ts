import { describe, expect, test } from 'vitest';
import { FILE_CONFLICT_KEY, fileSaveLight, type FileSaveState } from './file-save-light';

const BASE: FileSaveState = { writable: true, dirty: false, saving: false, stale: false, failed: false };

describe('fileSaveLight', () => {
    test('clean is green, dirty and saving are yellow, unwritable is dim', () => {
        expect(fileSaveLight(BASE).tone).toBe('saved');
        expect(fileSaveLight({ ...BASE, dirty: true }).tone).toBe('pending');
        expect(fileSaveLight({ ...BASE, dirty: true, saving: true }).labelKey).toBe('opscenter.cell.notes.saving');
        expect(fileSaveLight({ ...BASE, writable: false, dirty: true }).tone).toBe('off');
    });
    test('an error outranks unsaved text: stale names the conflict, failed the failure', () => {
        expect(fileSaveLight({ ...BASE, dirty: true, stale: true })).toMatchObject({ tone: 'error', labelKey: FILE_CONFLICT_KEY });
        expect(fileSaveLight({ ...BASE, dirty: true, failed: true })).toMatchObject({ tone: 'error', wordKey: 'opscenter.cell.notes.word.failed' });
    });
});
