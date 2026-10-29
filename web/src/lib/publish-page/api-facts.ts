import { bag, call, num, text } from './api';
import type { Facts, LocalCheck, LocalSend } from './types';

export interface ItemSend extends LocalSend {
    media_submission_id: string;
}

export interface ItemFacts extends Facts {
    kind: string;
    name: string;
    harness: string;
    file_count: number;
    total_bytes: number;
    files: { path: string; size: number }[];
    license_file: boolean;
    license: string;
    grade: string;
    description_tokens_est: number;
    sends: ItemSend[];
}

const MAX_LISTED = 20;
const MAX_FILES = 500;

function parseCheck(raw: unknown): LocalCheck {
    const row = bag(raw);
    const findings = (Array.isArray(row.findings) ? row.findings : []).slice(0, MAX_LISTED).map((f) => ({ code: text(bag(f).code, 64), path: text(bag(f).path, 300) })).filter((f) => f.code && f.path);
    return { version: text(row.version, 40), ok: row.ok === true, at: text(row.at, 40), summary: text(row.summary, 400), grade: text(row.grade, 4), files: num(row.files), bytes: num(row.bytes), digest: text(row.digest, 128), findings };
}

function parseSend(raw: unknown): ItemSend {
    const row = bag(raw);
    return { submission_id: text(row.submission_id, 64), version: text(row.version, 40), sent_at: text(row.sent_at, 40), hero: text(row.hero, 20), media_submission_id: text(row.media_submission_id, 64), hero_sha: text(row.hero_sha, 64) };
}

export function parseFacts(body: unknown, location: string): ItemFacts {
    const row = bag(body);
    return {
        location,
        kind: text(row.kind, 20),
        name: text(row.name, 80),
        harness: text(row.harness, 20),
        file_count: num(row.file_count) ?? 0,
        total_bytes: num(row.total_bytes) ?? 0,
        files: (Array.isArray(row.files) ? row.files : []).slice(0, MAX_FILES).map((f) => {
            const file = bag(f);
            return { path: text(file.path, 300), size: num(file.size) ?? 0 };
        }),
        license_file: row.license_file === true,
        license: text(row.license, 80),
        grade: text(row.grade, 4),
        description_tokens_est: num(bag(row.cost).description_tokens_est) ?? 0,
        declared_version: text(row.declared_version, 40),
        changed_files: num(row.changed_files) ?? 0,
        changed_at: text(row.changed_at, 40),
        made_at: text(row.made_at, 40),
        sends: (Array.isArray(row.sends) ? row.sends : []).slice(0, MAX_LISTED).map(parseSend),
        checks: (Array.isArray(row.checks) ? row.checks : []).slice(0, MAX_LISTED).map(parseCheck),
    };
}

export async function fetchFacts(location: string): Promise<ItemFacts> {
    return parseFacts(await call<unknown>(`/catalog/publish/items/${encodeURIComponent(location)}`), location);
}
