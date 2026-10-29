import { AdminApi, type Refusal } from './admin.js';
import { refusalOf } from './refusal-of';
import { listNotes, markNote, type NoteRow, type NoteStatus } from './notes.js';

/* the notes panel */
export interface NotesHost {
    readonly status: NoteStatus;
    readonly notes: NoteRow[];
    readonly loaded: boolean;
    readonly busy: boolean;
    readonly refusal: Refusal | null;
    loadNotes(status: NoteStatus): Promise<void>;
    mark(noteId: string, read: boolean): Promise<void>;
    reset(): void;
}

export function createNotesHost(deps: {
    api: AdminApi;
    onUnauthorized?: () => void;
}): NotesHost {
    const { api, onUnauthorized } = deps;

    let status = $state<NoteStatus>('unread');
    let notes = $state<NoteRow[]>([]);
    let loaded = $state(false);
    let busy = $state(false);
    let refusal = $state<Refusal | null>(null);

    async function guard(work: () => Promise<void>): Promise<boolean> {
        busy = true;
        refusal = null;
        try {
            await work();
            return true;
        } catch (error) {
            const shaped = refusalOf(error);
            if (shaped.status === 401) onUnauthorized?.();
            refusal = shaped;
            return false;
        } finally {
            busy = false;
        }
    }

    return {
        get status() {
            return status;
        },
        get notes() {
            return notes;
        },
        get loaded() {
            return loaded;
        },
        get busy() {
            return busy;
        },
        get refusal() {
            return refusal;
        },

        async loadNotes(wanted: NoteStatus): Promise<void> {
            status = wanted;
            await guard(async () => {
                notes = await listNotes(api, wanted);
                loaded = true;
            });
        },

        async mark(noteId: string, read: boolean): Promise<void> {
            const ok = await guard(async () => {
                await markNote(api, noteId, read);
            });
            if (ok) notes = notes.filter((row) => row.note_id !== noteId);
        },

        reset(): void {
            notes = [];
            loaded = false;
            status = 'unread';
            refusal = null;
        },
    };
}
