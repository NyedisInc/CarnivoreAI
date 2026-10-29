import { openModal } from '../modal';
import { whenLegacyBootComplete } from '../legacy-boot';
import { isSignedIn, refreshAccount } from './account-store.svelte';
import type { AccountFeature } from './features';
import { requireAccount } from './funnel';
import { prefsHydrated, readWelcomeSeen, writeWelcomeSeen } from './welcome-flag';
import WelcomeModal from './WelcomeModal.svelte';

const HYDRATE_POLL_MS = 500;
const HYDRATE_TRIES = 40;

export interface WelcomeDeps {
    hydrated: () => boolean;
    seen: () => boolean;
    markSeen: () => Promise<void>;
    loadAccount: () => Promise<void>;
    signedIn: () => boolean;
    open: () => Promise<'signin' | 'later' | null>;
    signIn: () => void;
}

export function realWelcomeDeps(): WelcomeDeps {
    return {
        hydrated: prefsHydrated,
        seen: readWelcomeSeen,
        markSeen: writeWelcomeSeen,
        loadAccount: refreshAccount,
        signedIn: isSignedIn,
        open: () => openModal<'signin' | 'later', Record<string, unknown>>(WelcomeModal as never, {}),
        signIn: () => void requireAccount({ feature: 'welcome' as AccountFeature, src: 'welcome', resume: () => {} }),
    };
}

export async function runWelcome(deps: WelcomeDeps): Promise<'shown' | 'skipped'> {
    if (!deps.hydrated() || deps.seen()) return 'skipped';
    if (!deps.signedIn()) await deps.loadAccount();
    if (deps.seen()) return 'skipped';
    if (deps.signedIn()) {
        await deps.markSeen();
        return 'skipped';
    }
    const choice = await deps.open();
    await deps.markSeen();
    if (choice === 'signin') deps.signIn();
    return 'shown';
}

function runWhenHydrated(deps: WelcomeDeps, triesLeft: number): void {
    if (deps.hydrated()) {
        void runWelcome(deps).catch((err) => console.warn('[welcome] failed', err));
    } else if (triesLeft > 0) {
        setTimeout(() => runWhenHydrated(deps, triesLeft - 1), HYDRATE_POLL_MS);
    }
}

export function installWelcome(): void {
    whenLegacyBootComplete(window, () => runWhenHydrated(realWelcomeDeps(), HYDRATE_TRIES));
}
