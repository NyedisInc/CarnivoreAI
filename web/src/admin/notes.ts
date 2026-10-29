import { AdminApi } from './admin.js';

export type NoteStatus = 'unread' | 'read';

export interface NoteRow {
    note_id: string;
    item_id: string;
    text: string;
    sender_id: string;
    sender_login: string;
    created_at: string;
    status: NoteStatus;
    read_at: string | null;
}

export async function listNotes(
    api: AdminApi,
    status: NoteStatus,
): Promise<NoteRow[]> {
    const body = (await api.call(
        'GET',
        '/notes?status=' + encodeURIComponent(status),
        null,
        true,
    )) as Record<string, unknown>;
    return Array.isArray(body?.notes) ? (body.notes as NoteRow[]) : [];
}

export async function markNote(
    api: AdminApi,
    noteId: string,
    read: boolean,
): Promise<NoteRow> {
    const action = read ? 'read' : 'unread';
    return (await api.call(
        'POST',
        '/notes/' + encodeURIComponent(noteId) + '/' + action,
        null,
        true,
    )) as NoteRow;
}
