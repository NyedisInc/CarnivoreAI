import { isAccountLoaded, isSignedIn, refreshAccount } from '../carnivore-account/account-store.svelte';
import type { AccountFeature } from '../carnivore-account/features';
import { requireAccount } from '../carnivore-account/funnel';
import { isGateRefusal } from '../community/community';
import type { PublishAccount, PublishHost } from './publish';

export const GATE_CANCELLED = Symbol('register-gate-cancelled');

export interface RegisterGate {
    readonly open: boolean;
    readonly account: PublishAccount | null;
    readonly failure: string | null;
    guard<T>(action: () => Promise<T>): Promise<T | typeof GATE_CANCELLED>;
    registered(): void;
    dismiss(): void;
}

export function guarded<T>(
    gate: RegisterGate | undefined,
    action: () => Promise<T>,
): Promise<T | typeof GATE_CANCELLED> {
    return gate ? gate.guard(action) : action();
}

/* could not be read */
export function createRegisterGate(
    host: () => PublishHost,
    failureText: string,
    feature: AccountFeature = 'comment',
): RegisterGate {
    let open = $state(false);
    let account = $state<PublishAccount | null>(null);
    let failure = $state<string | null>(null);
    let known: boolean | null = null;
    let waiting: Promise<boolean> | null = null;
    let settle: ((ok: boolean) => void) | null = null;

    async function signedIn(): Promise<boolean> {
        await refreshAccount();
        if (!isAccountLoaded() || isSignedIn()) return true;
        return new Promise<boolean>((resolve) => {
            void requireAccount({ feature, src: 'register_gate', resume: () => resolve(true), cancelled: () => resolve(false) });
        });
    }

    async function read(): Promise<void> {
        failure = null;
        try {
            account = await host().account();
            known = account.registered;
        } catch {
            failure = failureText;
        }
    }

    function prompt(): Promise<boolean> {
        if (waiting) return waiting;
        open = true;
        waiting = new Promise<boolean>((resolve) => { settle = resolve; });
        if (!account || account.registered) void read();
        return waiting;
    }

    function finish(ok: boolean): void {
        open = false;
        const done = settle;
        waiting = null;
        settle = null;
        done?.(ok);
    }

    return {
        get open() { return open; },
        get account() { return account; },
        get failure() { return failure; },
        async guard<T>(action: () => Promise<T>): Promise<T | typeof GATE_CANCELLED> {
            if (known !== true && !(await signedIn())) return GATE_CANCELLED;
            if (known !== true) {
                await read();
                if (known === false && !(await prompt())) return GATE_CANCELLED;
            }
            try {
                return await action();
            } catch (error) {
                if (!isGateRefusal(error)) throw error;
                known = false;
                if (!(await prompt())) return GATE_CANCELLED;
                return action();
            }
        },
        registered() {
            known = true;
            finish(true);
        },
        dismiss() { finish(false); },
    };
}
