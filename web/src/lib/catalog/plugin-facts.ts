import { PLUGIN_PART_KEYS } from '../../../../client/js/labels/catalog-kind.js';
import type { PreviewFile } from './types';

export interface PluginPart {
    prefix: string;
    labelKey: string;
    files: number;
}

export interface PluginFacts {
    name: string | null;
    version: string | null;
    description: string | null;
    parts: readonly PluginPart[];
}

const NOTHING: PluginFacts = {
    name: null,
    version: null,
    description: null,
    parts: [],
};

export function parsePluginManifest(
    text: string | null | undefined,
): Record<string, unknown> | null {
    if (typeof text !== 'string' || !text.trim()) return null;
    try {
        const parsed: unknown = JSON.parse(text);
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
            return null;
        }
        return parsed as Record<string, unknown>;
    } catch {
        return null;
    }
}

function filePath(file: PreviewFile | null | undefined): string {
    const raw = file && typeof file.path === 'string' ? file.path.trim() : '';
    return raw.startsWith('./') ? raw.slice(2) : raw;
}

export function pluginParts(
    files: readonly PreviewFile[] | null | undefined,
): readonly PluginPart[] {
    if (!Array.isArray(files)) return [];
    const paths = files.map(filePath).filter((path) => path !== '');

    const parts: PluginPart[] = [];
    for (const [prefix, labelKey] of Object.entries(PLUGIN_PART_KEYS)) {
        const count = prefix.endsWith('/')
            ? paths.filter((path) => path.startsWith(prefix)).length
            : paths.filter((path) => path === prefix).length;
        if (count > 0) parts.push({ prefix, labelKey, files: count });
    }
    return parts;
}

export function pluginFacts(
    text: string | null | undefined,
    files: readonly PreviewFile[] | null | undefined,
): PluginFacts {
    const parts = pluginParts(files);
    const manifest = parsePluginManifest(text);
    if (!manifest) return { ...NOTHING, parts };

    const trimmed = (value: unknown): string | null =>
        typeof value === 'string' && value.trim() ? value.trim() : null;

    return {
        name: trimmed(manifest.name),
        version: trimmed(manifest.version),
        description: trimmed(manifest.description),
        parts,
    };
}
