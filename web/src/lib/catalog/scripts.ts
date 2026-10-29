import { mcpServers } from './mcp';
import type { InstallPreview, PreviewFile } from './types';

export const SCRIPT_PREFIX = 'scripts/';

export function isScriptFile(file: PreviewFile | null | undefined): boolean {
    if (!file) return false;
    if (file.exec === true) return true;
    const path = typeof file.path === 'string' ? file.path.trim() : '';
    if (!path) return false;
    const normalised = path.startsWith('./') ? path.slice(2) : path;
    return normalised.startsWith(SCRIPT_PREFIX);
}

export function scriptFiles(preview: InstallPreview | null | undefined): PreviewFile[] {
    const files = preview && Array.isArray(preview.files) ? preview.files : [];
    return files.filter((file) => isScriptFile(file));
}

export function needsScriptConsent(preview: InstallPreview | null | undefined): boolean {
    return scriptFiles(preview).length > 0 || mcpServers(preview).length > 0;
}

export function consentBlock(
    preview: InstallPreview | null | undefined,
): { digest: string; body_sha: string; scripts: true } | null {
    if (!preview) return null;
    const digest = typeof preview.digest === 'string' ? preview.digest.trim() : '';
    const bodySha = typeof preview.body_sha === 'string' ? preview.body_sha.trim() : '';
    if (!digest || !bodySha) return null;
    return { digest, body_sha: bodySha, scripts: true };
}
