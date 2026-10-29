import type { AdminApi } from './admin.js';

export interface Challenge {
    publicKey: Record<string, unknown>;
    challenge_token: string;
}

export interface PasskeyItem {
    id: string;
    label: string;
    created_at: number;
    last_used_at: number;
    synced: boolean;
}

export interface PasskeyStatus {
    configured: boolean;
    required: boolean;
    enrolled: boolean;
    can_enroll_first: boolean;
    window_open: boolean;
    credentials: PasskeyItem[];
}

const BASE = '/auth/passkey';

function record(value: unknown): Record<string, unknown> {
    return value && typeof value === 'object' ? (value as Record<string, unknown>) : {};
}

export class PasskeyApi {
    private readonly api: AdminApi;

    constructor(api: AdminApi) {
        this.api = api;
    }

    /* passkey sign in */
    async health(): Promise<boolean> {
        const body = record(await this.api.call('GET', '/health', null, false));
        return record(body.providers).passkey === true;
    }

    async loginOptions(): Promise<Challenge> {
        return this.challenge(await this.api.call('POST', BASE + '/login/options', {}, false));
    }

    async loginVerify(body: Record<string, unknown>): Promise<{ access_token: string; login: string }> {
        const out = record(await this.api.call('POST', BASE + '/login/verify', body, false));
        return {
            access_token: typeof out.access_token === 'string' ? out.access_token : '',
            login: typeof out.login === 'string' ? out.login : '',
        };
    }

    async registerOptions(mode: 'first' | 'add', enrolCode: string): Promise<Challenge> {
        const body: Record<string, unknown> = { mode };
        if (mode === 'first') body.enrol_code = enrolCode;
        return this.challenge(await this.api.call('POST', BASE + '/register/options', body, true));
    }

    async registerVerify(body: Record<string, unknown>): Promise<void> {
        await this.api.call('POST', BASE + '/register/verify', body, true);
    }

    async credentials(): Promise<PasskeyStatus> {
        const out = record(await this.api.call('GET', BASE + '/credentials', null, true));
        const list = Array.isArray(out.credentials) ? out.credentials : [];
        return {
            configured: out.configured === true,
            required: out.required === true,
            enrolled: out.enrolled === true,
            can_enroll_first: out.can_enroll_first === true,
            window_open: out.window_open === true,
            credentials: list.map((item) => {
                const c = record(item);
                return {
                    id: String(c.id || ''),
                    label: String(c.label || ''),
                    created_at: Number(c.created_at || 0),
                    last_used_at: Number(c.last_used_at || 0),
                    synced: c.synced === true,
                };
            }),
        };
    }

    async deleteCredential(id: string): Promise<void> {
        await this.api.call('DELETE', BASE + '/credentials/' + encodeURIComponent(id), null, true);
    }

    private challenge(value: unknown): Challenge {
        const out = record(value);
        return {
            publicKey: record(out.publicKey),
            challenge_token: typeof out.challenge_token === 'string' ? out.challenge_token : '',
        };
    }
}
