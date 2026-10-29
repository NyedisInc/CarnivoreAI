/* CANNOT DETERMINE */
import { RUNNING_SESSION_KEYS } from '../../../../client/js/labels/running-session.js';
import type { LaunchedWith, RunningSessionRow } from '../sessions/types';

export type RenameState = 'renameable' | 'unavailable' | 'unknown_owner';

export interface RenamePencilView {
    state: RenameState;
    renameKey: string | null;
    reasonKey: string;
    className: string;
}

/* running sessions */
export function renamePencilView(row: RunningSessionRow): RenamePencilView {
    const renameKey = row.session_id || row.name || null;
    if (renameKey) {
        return {
            state: 'renameable',
            renameKey,
            reasonKey: RUNNING_SESSION_KEYS.renameAction,
            className: 'running-session-rename',
        };
    }
    if (row.created_by_cloude == null) {
        return {
            state: 'unknown_owner',
            renameKey: null,
            reasonKey: RUNNING_SESSION_KEYS.renameUnknownOwner,
            className: 'running-session-rename-unavailable',
        };
    }
    return {
        state: 'unavailable',
        renameKey: null,
        reasonKey: row.created_by_cloude
            ? RUNNING_SESSION_KEYS.renameUnopened
            : RUNNING_SESSION_KEYS.renameUnadopted,
        className: 'running-session-rename-unavailable',
    };
}

export function sessionRowId(row: RunningSessionRow): string | null {
    const id = row.session_row_id;
    if (id === null || id === undefined || (id as unknown) === '') return null;
    return String(id);
}

export function offersFork(row: RunningSessionRow): boolean {
    return !!row.created_by_cloude;
}

export interface WrapperPillView {
    label: string;
}

/* label: ' */
export function wrapperPillView(
    label: string | null | undefined,
): WrapperPillView | null {
    if (typeof label !== 'string') return null;
    const text = label.trim();
    if (!text) return null;
    return { label: text };
}

/* label: ' */
export function launchedWithText(
    launched: LaunchedWith | null | undefined,
    t: (key: string, params?: Record<string, unknown> | null) => string,
): string | null {
    if (!launched || typeof launched.label !== 'string' || !launched.label.trim()) return null;
    const parts = [launched.label.trim(), launched.account, launched.model].filter(
        (p): p is string => typeof p === 'string' && p.trim() !== '',
    );
    return t('launch_picker.launched_with', { text: parts.join(' · ') });
}

export interface ThemeCueView {
    themeId: string;
    accent: string;
    name: string;
}

export interface ThemeColors {
    accent: string;
    label: string;
}

/**
 * The theme cue for one row, or null for all three not-themed cases.
 *
 * Description: the COLOURS come from `client/js/session-theme-tint.js`,
 *   which stays legacy because the sidebar row draws the same cue from
 *   it. Only its DATA half is consumed here (`colorsFor`), never its
 *   markup half, so there is one source for what a theme looks like and
 *   two renderers for it - the same arrangement the glyphs have.
 *
 *   AN UNKNOWN ID IS NOT CACHED BY THAT MODULE, on purpose: the theme
 *   registry fills in asynchronously, so "unknown right now" has to stay
 *   askable on the next paint. This function inherits that, which is why
 *   it takes the lookup as an argument rather than memoizing anything.
 *
 *   THE ID IS SCRUBBED TO `[A-Za-z0-9_-]`. Svelte escapes attribute
 *   values, so this is not an injection guard; it is what keeps the
 *   attribute a stylesheet can select on, and an id that survives as
 *   empty yields an untinted row rather than a partial one.
 * Inputs: themeId - the row's `pinned_theme`. colorsFor - the lookup.
 * Output: ThemeCueView | null.
 * Example: themeCueView('dracula', lookup)
 */
export function themeCueView(
    themeId: string | null | undefined,
    colorsFor: (id: string) => ThemeColors | null,
): ThemeCueView | null {
    if (!themeId) return null;
    const safeId = String(themeId).replace(/[^a-zA-Z0-9_-]/g, '');
    if (!safeId) return null;
    const colors = colorsFor(themeId);
    if (!colors || !colors.accent) return null;
    return {
        themeId: safeId,
        accent: colors.accent,
        name: colors.label || String(themeId),
    };
}
