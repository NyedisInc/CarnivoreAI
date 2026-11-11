import { describe, expect, test, vi } from 'vitest';
import { ApiError } from '../../opscenter/api/auth.svelte';
import { createDropFlow, folderOfPicked, pathOfDrop } from './drop-folder';

const SHEET = {
    code: 'consent_required', kind: 'plugin', name: 'clock', digest: 'd'.repeat(64), digest_prefix: 'dddddddddddd', body_sha: 'b'.repeat(64),
    body: '{}', publisher: 'local', requires_consent: true, total_bytes: 1, mcp_servers: [], files: [],
};
const CONSENT = { digest: SHEET.digest, body_sha: SHEET.body_sha, scripts: true } as const;
const needsConsent = () => new ApiError('consent', 409, null, { detail: SHEET });
const dir = { isDirectory: true };
const file = { isDirectory: false };

function drop(entry: { isDirectory: boolean } | null, path: string) {
    const files = [{ name: 'clock' }] as unknown as FileList;
    const dt = { files, items: [{ kind: 'file', webkitGetAsEntry: () => entry }] } as unknown as DataTransfer;
    return { dt, bridge: { droppedPaths: () => [path] } };
}

describe('pathOfDrop', () => {
    test('a dropped folder gives its real path from the desktop bridge', () => {
        const { dt, bridge } = drop(dir, '/Users/me/dev/clock');
        expect(pathOfDrop(dt, bridge)).toEqual({ path: '/Users/me/dev/clock' });
    });
    test('a dropped file is not a folder', () => {
        const { dt, bridge } = drop(file, '/Users/me/a.txt');
        expect(pathOfDrop(dt, bridge)).toEqual({ problem: 'not_folder' });
    });
    test('a browser has no bridge, so no path', () => {
        const { dt } = drop(dir, '');
        expect(pathOfDrop(dt, null)).toEqual({ problem: 'no_path' });
    });
});

describe('folderOfPicked', () => {
    test('the folder is the picked file path minus its path inside the folder', () => {
        const picked = { webkitRelativePath: 'clock/sub/main.py' } as unknown as File;
        expect(folderOfPicked(picked, '/Users/me/dev/clock/sub/main.py')).toBe('/Users/me/dev/clock');
    });
    test('a path that does not end with the relative path gives nothing', () => {
        expect(folderOfPicked({ webkitRelativePath: 'clock/main.py' } as unknown as File, '/elsewhere/main.py')).toBeNull();
    });
});

describe('createDropFlow', () => {
    test('a folder that runs code opens the consent sheet, and cancel installs nothing', async () => {
        const loadFolder = vi.fn(async () => { throw needsConsent(); });
        const flow = createDropFlow({ loadFolder });
        await flow.drop('/Users/me/dev/clock');
        expect(flow.sheet?.name).toBe('clock');
        flow.cancel();
        expect(flow.sheet).toBeNull();
        expect(loadFolder).toHaveBeenCalledTimes(1);
        expect(loadFolder).toHaveBeenCalledWith('/Users/me/dev/clock', null);
    });
    test('confirming sends the consent the sheet named, once', async () => {
        const loadFolder = vi.fn()
            .mockRejectedValueOnce(needsConsent())
            .mockResolvedValueOnce(undefined);
        const flow = createDropFlow({ loadFolder });
        await flow.drop('/p');
        await flow.confirm(CONSENT);
        expect(loadFolder).toHaveBeenLastCalledWith('/p', null, CONSENT);
        expect(flow.sheet).toBeNull();
    });
    test('a refusal is kept for the page to word; a plain load leaves no sheet', async () => {
        const flow = createDropFlow({ loadFolder: async () => { throw new ApiError('no', 422, 'source_not_downloaded', null); } });
        await flow.drop('/p');
        expect(flow.sheet).toBeNull();
        expect(flow.error).toBeInstanceOf(ApiError);
    });
});
