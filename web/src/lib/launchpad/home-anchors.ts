/* the home screen */

export const SCREEN_ID = 'launchpad-screen';

export const STATUS_ANCHOR_ID = 'home-bar-status';

export const STATUS_LABEL_ID = 'home-bar-status-text';

export const HOME_ANCHOR_IDS: readonly string[] = [
    SCREEN_ID,
    STATUS_ANCHOR_ID,
    STATUS_LABEL_ID,
];

export function missingHomeAnchors(doc: Document | null | undefined): string[] {
    if (!doc) return [...HOME_ANCHOR_IDS];
    return HOME_ANCHOR_IDS.filter((id) => !doc.getElementById(id));
}
