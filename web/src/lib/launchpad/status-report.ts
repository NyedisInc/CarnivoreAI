import { hostDocument } from '../sessions/env';
import { HOME_KEYS, refusedProjectNotice } from '../../../../client/js/labels/home-screen.js';
import type { Translate } from './recent';

export const ERROR_CARD_TTL_MS = 12000;

export const ERROR_STACK_ID = 'launchpad-error-stack';

export function updateStatus(message: string): void {
    const doc = hostDocument();
    const el = doc?.getElementById('statusText');
    if (!el) return;
    el.setAttribute('data-status', message);
    el.setAttribute('aria-label', message);
}

export function showError(message: string, t: Translate): void {
    console.error('CloudeWeb: home screen error:', message);
    const doc = hostDocument();
    if (!doc || !doc.body) return;
    try {
        let host = doc.getElementById(ERROR_STACK_ID);
        if (!host) {
            host = doc.createElement('div');
            host.id = ERROR_STACK_ID;
            doc.body.appendChild(host);
        }
        const card = doc.createElement('div');
        card.className = 'launchpad-error-card';
        card.setAttribute('role', 'alert');
        const text = doc.createElement('span');
        text.className = 'launchpad-error-text';
        text.textContent = message;
        const close = doc.createElement('button');
        close.type = 'button';
        close.className = 'launchpad-error-dismiss';
        close.setAttribute('aria-label', t(HOME_KEYS.errorDismiss));
        close.textContent = '×';
        const remove = () => {
            if (card.parentNode) card.parentNode.removeChild(card);
        };
        close.addEventListener('click', remove);
        card.appendChild(text);
        card.appendChild(close);
        host.appendChild(card);
        setTimeout(remove, ERROR_CARD_TTL_MS);
    } catch (error) {
        console.error('CloudeWeb: could not render the error card:', error);
    }
}

export interface RefusableProject {
    name?: string | null;
    root?: string | null;
    path?: string | null;
}

export interface PresenceRow {
    presence?: string | null;
    presence_detail?: string | null;
}

export function explainRefusedProject(
    project: RefusableProject | null | undefined,
    presence: PresenceRow | null | undefined,
    t: Translate,
): 'missing' | 'unreachable' | 'unknown' {
    const notice = refusedProjectNotice(
        {
            name: project?.name ?? null,
            path: project?.root || project?.path || null,
            presence: presence?.presence ?? 'unchecked',
            detail: presence?.presence_detail ?? null,
        },
        t,
    );
    showError(notice.text, t);
    return notice.rung === 'missing' || notice.rung === 'unreachable'
        ? notice.rung
        : 'unknown';
}
