import { authFetch } from '../sdk';
import { num, obj, objects, ROUTE, str, type Fetcher } from './crate-api';

export type FolderName = 'primary' | 'second';

export interface FolderCrate {
    readonly folder: FolderName;
    readonly name: string;
    readonly size: number | null;
    readonly writtenAt: string | null;
    readonly share: boolean;
    readonly encrypted: boolean;
    readonly bundleId: string | null;
    readonly projectRoot: string | null;
}

export interface UploadedCrate {
    readonly name: string;
    readonly size: number | null;
    readonly sidecar: boolean;
    readonly projectRoot: string | null;
}

const CRATE_FILE = /^crate-[A-Za-z0-9._-]{3,90}\.crate(\.age)?$/;
const HEX64 = /^[0-9a-fA-F]{64}(?=\s|$)/;

function parseFolderCrate(folder: FolderName, raw: Record<string, unknown>): FolderCrate | null {
    const name = str(raw.name);
    if (!name) return null;
    const mtime = num(raw.mtime);
    return {
        folder, name, size: num(raw.size), writtenAt: mtime === null ? null : new Date(mtime * 1000).toISOString(),
        share: raw.share === true, encrypted: raw.encrypted === true, bundleId: str(raw.bundle_id), projectRoot: str(raw.project_root),
    };
}

export async function fetchFolderCrates(folder: FolderName, fetcher: Fetcher = authFetch): Promise<FolderCrate[]> {
    const answer = obj(await fetcher<unknown>(`${ROUTE}/folders/${folder}/crates`));
    return objects(answer?.crates)
        .map((row) => parseFolderCrate(folder, row))
        .filter((c): c is FolderCrate => c !== null)
        .sort((a, b) => (b.writtenAt ?? '').localeCompare(a.writtenAt ?? ''));
}

export function unrecorded(crates: readonly FolderCrate[]): FolderCrate[] {
    return crates.filter((c) => c.bundleId === null);
}

export function sidecarHex(text: string): string | null {
    const found = HEX64.exec(text.trim());
    return found ? found[0].toLowerCase() : null;
}

export interface PickedCrate {
    readonly crate: File;
    readonly sidecar: File | null;
}

export function pickCrate(files: readonly File[]): PickedCrate | null {
    const crate = files.find((f) => CRATE_FILE.test(f.name));
    if (!crate) return null;
    const sidecar = files.find((f) => f.name === `${crate.name}.sha256`) ?? files.find((f) => f.name.endsWith('.sha256')) ?? null;
    return { crate, sidecar };
}

export async function uploadCrate(crate: File, sha256: string | null, fetcher: Fetcher = authFetch): Promise<UploadedCrate> {
    const headers: Record<string, string> = { 'Content-Type': 'application/octet-stream', 'X-Crate-Name': crate.name };
    if (sha256) headers['X-Crate-Sha256'] = sha256;
    const answer = obj(await fetcher<unknown>(`${ROUTE}/folders/primary/crates/upload`, { method: 'POST', headers, body: crate }));
    return { name: str(answer?.name) ?? crate.name, size: num(answer?.size), sidecar: answer?.sidecar === true, projectRoot: str(answer?.project_root) };
}

export interface PickRefused {
    readonly refused: 'not_a_crate' | 'bad_checksum_file';
}

function readText(file: File): Promise<string> {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result ?? ''));
        reader.onerror = () => reject(reader.error ?? new Error('the checksum file could not be read'));
        reader.readAsText(file);
    });
}

export async function sendPicked(files: readonly File[], fetcher: Fetcher = authFetch): Promise<UploadedCrate | PickRefused> {
    const pick = pickCrate(files);
    if (!pick) return { refused: 'not_a_crate' };
    let sha256: string | null = null;
    if (pick.sidecar) {
        sha256 = sidecarHex(await readText(pick.sidecar));
        if (!sha256) return { refused: 'bad_checksum_file' };
    }
    return uploadCrate(pick.crate, sha256, fetcher);
}

export type RemoveTarget = { readonly bundleId: string } | { readonly folder: FolderName; readonly name: string };

export interface RemovedCrates {
    readonly removed: readonly { readonly folder: string; readonly name: string }[];
    readonly localRemoved: boolean;
}

export async function removeCrate(target: RemoveTarget, alsoSecond = false, fetcher: Fetcher = authFetch): Promise<RemovedCrates> {
    const named = 'bundleId' in target ? { bundle_id: target.bundleId } : { folder: target.folder, name: target.name };
    const answer = obj(await fetcher<unknown>(`${ROUTE}/crates/remove`, { method: 'POST', body: JSON.stringify({ ...named, also_second: alsoSecond }) }));
    return {
        removed: objects(answer?.removed).map((r) => ({ folder: str(r.folder) ?? '', name: str(r.name) ?? '' })),
        localRemoved: answer?.local_removed === true,
    };
}
