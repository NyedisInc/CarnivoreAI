import { isAccountLoaded, isSignedIn, onAccountChange, refreshAccount } from './account-store.svelte';
import { isGuestOk, type AccountFeature, type FunnelSource } from './features';

export interface SignInRequest {
    feature: AccountFeature;
    src: FunnelSource;
}

export const SIGNIN_REQUEST_EVENT = 'cloude:account-signin-request';

let opener: ((request: SignInRequest) => void) | null = null;
let pending: (() => void) | null = null;
let pendingCancelled: (() => void) | null = null;
let wasSignedIn = false;
let stopWatching: (() => void) | null = null;

export function registerSignInOpener(fn: ((request: SignInRequest) => void) | null): void {
    opener = fn;
}

export function cancelPendingAccount(): void {
    pending = null;
    const told = pendingCancelled;
    pendingCancelled = null;
    told?.();
}

function onChange(): void {
    const now = isSignedIn();
    if (now && pending) {
        const run = pending;
        pending = null;
        pendingCancelled = null;
        run();
    } else if (!now && wasSignedIn) {
        cancelPendingAccount();
    }
    wasSignedIn = now;
}

export async function requireAccount(args: {
    feature: AccountFeature;
    src: FunnelSource;
    resume: () => void;
    cancelled?: () => void;
}): Promise<'resumed' | 'prompted'> {
    if (!isAccountLoaded()) await refreshAccount();
    if (isSignedIn() || isGuestOk(args.feature)) {
        args.resume();
        return 'resumed';
    }
    if (!stopWatching) {
        wasSignedIn = isSignedIn();
        stopWatching = onAccountChange(onChange);
    }
    const alreadyOpen = pending !== null;
    pendingCancelled?.();
    pendingCancelled = args.cancelled ?? null;
    pending = args.resume;
    if (!alreadyOpen) {
        if (opener) opener({ feature: args.feature, src: args.src });
        else window.dispatchEvent(new CustomEvent(SIGNIN_REQUEST_EVENT, { detail: { feature: args.feature, src: args.src } }));
    }
    return 'prompted';
}
