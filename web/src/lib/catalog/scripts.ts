import { mcpServers } from './mcp';
import type { InstallPreview, PreviewFile } from './types';

export const SCRIPT_PREFIX = 'scripts/';
const SCRIPT_PREFIXES = ['scripts/', 'hooks/', 'bin/', 'monitors/'] as const;
const SCRIPT_EXT_RE = /\.(?:sh|bash|zsh|fish|py|js|mjs|cjs|ts|tsx|mts|cts|jsx|rb|pl|php|ps1|bat|cmd|lua|awk|command)$/i;

export function isScriptFile(file: PreviewFile | null | undefined): boolean {
    if (!file) return false;
    if (file.exec === true) return true;
    const path = typeof file.path === 'string' ? file.path.trim() : '';
    if (!path) return false;
    const normalised = path.startsWith('./') ? path.slice(2) : path;
    const lower = normalised.toLowerCase();
    if (SCRIPT_PREFIXES.some((prefix) => lower.startsWith(prefix))) return true;
    return SCRIPT_EXT_RE.test(lower);
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
