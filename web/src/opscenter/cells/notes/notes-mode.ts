
export const NOTES_MODES = ['edit', 'preview'] as const;

export type NotesMode = (typeof NOTES_MODES)[number];

export function isNotesMode(value: unknown): value is NotesMode {
  return (NOTES_MODES as readonly unknown[]).includes(value);
}

export const NOTES_MODE_KEY = 'cloude_notes_preview';
