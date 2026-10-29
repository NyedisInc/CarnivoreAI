import { ApiRefusal } from './admin.js';

export interface CredentialsLike {
    get(options: { publicKey: Record<string, unknown> }): Promise<unknown>;
    create(options: { publicKey: Record<string, unknown> }): Promise<unknown>;
}

export type OptionsJson = Record<string, unknown>;

/* padding */
export function b64uEncode(data: ArrayBuffer | Uint8Array): string {
    const bytes = data instanceof Uint8Array ? data : new Uint8Array(data);
    let text = '';
    for (const byte of bytes) text += String.fromCharCode(byte);
    return btoa(text).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

/* padding */
export function b64uDecode(text: string): Uint8Array {
    const padded = text.replace(/-/g, '+').replace(/_/g, '/') + '==='.slice((text.length + 3) % 4);
    const raw = atob(padded);
    const out = new Uint8Array(raw.length);
    for (let i = 0; i < raw.length; i += 1) out[i] = raw.charCodeAt(i);
    return out;
}

function descriptors(list: unknown): Record<string, unknown>[] {
    if (!Array.isArray(list)) return [];
    return list.map((item) => {
        const entry = item as Record<string, unknown>;
        return { ...entry, id: b64uDecode(String(entry.id || '')) };
    });
}

export function requestOptions(json: OptionsJson): Record<string, unknown> {
    return {
        ...json,
        challenge: b64uDecode(String(json.challenge || '')),
        allowCredentials: descriptors(json.allowCredentials),
    };
}

export function creationOptions(json: OptionsJson): Record<string, unknown> {
    const user = (json.user || {}) as Record<string, unknown>;
    return {
        ...json,
        challenge: b64uDecode(String(json.challenge || '')),
        user: { ...user, id: b64uDecode(String(user.id || '')) },
        excludeCredentials: descriptors(json.excludeCredentials),
    };
}

interface RawCredential {
    rawId: ArrayBuffer;
    response: Record<string, ArrayBuffer | null | (() => string[])>;
}

function encodeOptional(value: unknown): string {
    return value ? b64uEncode(value as ArrayBuffer) : '';
}

export function assertionToWire(credential: unknown): Record<string, unknown> {
    const cred = credential as RawCredential;
    const r = cred.response;
    return {
        rawId: b64uEncode(cred.rawId),
        response: {
            clientDataJSON: encodeOptional(r.clientDataJSON),
            authenticatorData: encodeOptional(r.authenticatorData),
            signature: encodeOptional(r.signature),
            userHandle: encodeOptional(r.userHandle),
        },
    };
}

export function attestationToWire(credential: unknown): Record<string, unknown> {
    const cred = credential as RawCredential;
    const r = cred.response;
    const transports = typeof r.getTransports === 'function' ? (r.getTransports as () => string[])() : [];
    return {
        rawId: b64uEncode(cred.rawId),
        response: {
            clientDataJSON: encodeOptional(r.clientDataJSON),
            attestationObject: encodeOptional(r.attestationObject),
            transports,
        },
    };
}

export async function runCeremony(
    kind: 'get' | 'create',
    creds: CredentialsLike | undefined,
    publicKey: Record<string, unknown>,
): Promise<unknown> {
    if (!creds || typeof creds[kind] !== 'function') {
        throw new ApiRefusal({ status: 0, code: 'passkey_unsupported', params: {} });
    }
    let credential: unknown;
    try {
        credential = await creds[kind]({ publicKey });
    } catch (error) {
        throw new ApiRefusal({ status: 0, code: 'passkey_cancelled', params: {} });
    }
    if (!credential) throw new ApiRefusal({ status: 0, code: 'passkey_cancelled', params: {} });
    return credential;
}
