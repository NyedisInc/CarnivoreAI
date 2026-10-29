import { isAccountLoaded, isSignedIn, onAccountChange, refreshAccount } from './account-store.svelte';
import { isGuestOk, type AccountFeature, type FunnelSource } from './features';

export interface SignInRequest {
    feature: AccountFeature | null;
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

function runPending(): void {
    const run = pending;
    if (!run) return;
    pending = null;
    pendingCancelled = null;
    run();
}

function onChange(): void {
    const now = isSignedIn();
    if (now && pending) {
        runPending();
    } else if (!now && wasSignedIn) {
        cancelPendingAccount();
    }
    wasSignedIn = now;
}

export async function settleSignIn(): Promise<void> {
    try {
        await refreshAccount();
    } catch (error) {
        console.warn('[account] could not read the account after sign in', error);
    }
    if (isSignedIn()) runPending();
    else cancelPendingAccount();
}

export async function requireAccount(args: {
    feature: AccountFeature | null;
    src: FunnelSource;
    resume: () => void;
    cancelled?: () => void;
    joins?: boolean;
}): Promise<'resumed' | 'prompted'> {
    if (!isAccountLoaded()) await refreshAccount();
    if (isSignedIn() || (args.feature !== null && isGuestOk(args.feature))) {
        args.resume();
        return 'resumed';
    }
    if (!stopWatching) {
        wasSignedIn = isSignedIn();
        stopWatching = onAccountChange(onChange);
    }
    const alreadyOpen = pending !== null;
    if (alreadyOpen && args.joins) {
        const [held, heldCancelled] = [pending!, pendingCancelled];
        pending = () => { held(); args.resume(); };
        pendingCancelled = () => { heldCancelled?.(); args.cancelled?.(); };
        return 'prompted';
    }
    pendingCancelled?.();
    pendingCancelled = args.cancelled ?? null;
    pending = args.resume;
    if (!alreadyOpen) {
        if (opener) opener({ feature: args.feature, src: args.src });
        else window.dispatchEvent(new CustomEvent(SIGNIN_REQUEST_EVENT, { detail: { feature: args.feature, src: args.src } }));
    }
    return 'prompted';
}
