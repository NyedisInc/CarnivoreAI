import { identiconMarkup } from '../community/identicon';
import type { AccountIdentity } from '../drawer-hud/account-identity';

const ANON_AVATAR = '<svg class="anon spiral spiral-turn" data-spiral="" width="22" height="22" viewBox="-11 -11 22 22" aria-hidden="true" focusable="false">'
    + '<g><path fill="none" stroke="currentColor" stroke-width="2.2" d="M0.4 0.1 L0.6 0.3 L0.7 0.6 L0.8 0.9 L0.7 1.2 L0.6 1.6 L0.3 1.9 L-0.0 2.2 L-0.4 2.4 L-1.0 2.5 L-1.5 2.5 L-2.1 2.4 L-2.7 2.1 L-3.3 1.7 L-3.8 1.2 L-4.2 0.5 L-4.5 -0.3 L-4.6 -1.2 L-4.5 -2.1 L-4.3 -3.0 L-3.9 -3.9 L-3.2 -4.8 L-2.4 -5.5 L-1.5 -6.1 L-0.3 -6.5 L0.9 -6.7 L2.2 -6.7 L3.4 -6.4 L4.7 -5.9 L5.9 -5.1 L6.9 -4.1 L7.8 -2.9 L8.4 -1.4 L8.8 0.1 L8.9 1.7 L8.7 3.4 L8.1 5.1 L7.3 6.6 L6.1 8.0 L4.7 9.2 L3.0 10.2 L1.1 10.8 L-0.8 11.1 L-2.9 11.0 L-4.9 10.5 L-6.9 9.6 L-8.7 8.4 L-10.3 6.8 L-11.6 5.0 L-12.6 2.9 L-13.1 0.5 L-13.3 -1.9 L-12.9 -4.3 L-12.2 -6.7 L-11.0 -9.0 L-9.3 -11.0 L-7.3 -12.7 L-5.0 -14.1 L-2.4 -15.0 L0.4 -15.4 L3.2 -15.4 M-0.4 -0.1 L-0.6 -0.3 L-0.7 -0.6 L-0.8 -0.9 L-0.7 -1.2 L-0.6 -1.6 L-0.3 -1.9 L0.0 -2.2 L0.4 -2.4 L1.0 -2.5 L1.5 -2.5 L2.1 -2.4 L2.7 -2.1 L3.3 -1.7 L3.8 -1.2 L4.2 -0.5 L4.5 0.3 L4.6 1.2 L4.5 2.1 L4.3 3.0 L3.9 3.9 L3.2 4.8 L2.4 5.5 L1.5 6.1 L0.3 6.5 L-0.9 6.7 L-2.2 6.7 L-3.4 6.4 L-4.7 5.9 L-5.9 5.1 L-6.9 4.1 L-7.8 2.9 L-8.4 1.4 L-8.8 -0.1 L-8.9 -1.7 L-8.7 -3.4 L-8.1 -5.1 L-7.3 -6.6 L-6.1 -8.0 L-4.7 -9.2 L-3.0 -10.2 L-1.1 -10.8 L0.8 -11.1 L2.9 -11.0 L4.9 -10.5 L6.9 -9.6 L8.7 -8.4 L10.3 -6.8 L11.6 -5.0 L12.6 -2.9 L13.1 -0.5 L13.3 1.9 L12.9 4.3 L12.2 6.7 L11.0 9.0 L9.3 11.0 L7.3 12.7 L5.0 14.1 L2.4 15.0 L-0.4 15.4 L-3.2 15.4"/></g></svg>';

export function isMember(who: AccountIdentity | null): boolean {
    return !!who && who.kind === 'member' && who.name !== '';
}

export function avatarInnerHtml(who: AccountIdentity | null): string {
    return isMember(who) ? identiconMarkup(who!.name, 22) : ANON_AVATAR;
}

export function avatarHtml(who: AccountIdentity | null): string {
    return `<span class="session-sidebar-bar__avatar" data-kind="${isMember(who) ? 'member' : 'lurker'}" aria-hidden="true">${avatarInnerHtml(who)}</span>`;
}
