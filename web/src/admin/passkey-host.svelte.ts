/* passkey sign in */
import { ApiRefusal } from './admin.js';
import type { PasskeyApi, PasskeyItem } from './passkey-api.js';
import {
    assertionToWire,
    attestationToWire,
    creationOptions,
    requestOptions,
    runCeremony,
    type CredentialsLike,
} from './passkey.js';

export interface PasskeyHost {
    readonly items: PasskeyItem[];
    readonly configured: boolean;
    readonly enrolled: boolean;
    readonly canEnrollFirst: boolean;
    readonly loaded: boolean;
    load(): Promise<void>;
    enroll(mode: 'first' | 'add', code: string, label: string): Promise<boolean>;
    remove(id: string): Promise<void>;
}

export async function signInCeremony(
    pk: PasskeyApi,
    creds: CredentialsLike | undefined,
): Promise<string> {
    const options = await pk.loginOptions();
    const credential = await runCeremony('get', creds, requestOptions(options.publicKey));
    const answer = await pk.loginVerify({
        challenge_token: options.challenge_token,
        ...assertionToWire(credential),
    });
    return answer.access_token;
}

/* passkey sign in */
export function createPasskeyHost(deps: {
    pk: PasskeyApi;
    creds: () => CredentialsLike | undefined;
    guard: (work: () => Promise<void>) => Promise<boolean>;
    reauth: () => Promise<void>;
    onEnrolled: () => void;
}): PasskeyHost {
    const { pk, creds, guard, reauth, onEnrolled } = deps;
    let items = $state<PasskeyItem[]>([]);
    let configured = $state(false);
    let enrolled = $state(false);
    let canEnrollFirst = $state(false);
    let loaded = $state(false);

    async function fresh(work: () => Promise<void>): Promise<void> {
        try {
            await work();
        } catch (error) {
            if (error instanceof ApiRefusal && error.refusal.code === 'fresh_passkey_required') {
                await reauth();
                await work();
                return;
            }
            throw error;
        }
    }

    async function read(): Promise<void> {
        const status = await pk.credentials();
        configured = status.configured;
        enrolled = status.enrolled;
        canEnrollFirst = status.can_enroll_first;
        items = status.credentials;
        loaded = true;
    }

    return {
        get items() {
            return items;
        },
        get configured() {
            return configured;
        },
        get enrolled() {
            return enrolled;
        },
        get canEnrollFirst() {
            return canEnrollFirst;
        },
        get loaded() {
            return loaded;
        },

        async load(): Promise<void> {
            try {
                await read();
            } catch (error) {
                if (error instanceof ApiRefusal && error.refusal.code === 'passkey_not_configured') {
                    configured = false;
                    loaded = true;
                    return;
                }
                await guard(async () => {
                    throw error;
                });
            }
        },

        async enroll(mode: 'first' | 'add', code: string, label: string): Promise<boolean> {
            const work = async (): Promise<void> => {
                const options = await pk.registerOptions(mode, code.trim());
                const credential = await runCeremony('create', creds(), creationOptions(options.publicKey));
                const body: Record<string, unknown> = {
                    challenge_token: options.challenge_token,
                    label: label.trim(),
                    ...attestationToWire(credential),
                };
                if (mode === 'first') body.enrol_code = code.trim();
                await pk.registerVerify(body);
            };
            const ok = await guard(async () => {
                if (mode === 'add') await fresh(work);
                else await work();
            });
            if (!ok) return false;
            if (mode === 'first') onEnrolled();
            await guard(read);
            return true;
        },

        async remove(id: string): Promise<void> {
            const ok = await guard(() => fresh(() => pk.deleteCredential(id)));
            if (ok) await guard(read);
        },
    };
}
