import type { CatalogItem } from './types';

export const COMPAT_HARNESSES = ['claude', 'codex', 'app'] as const;

export const MAX_TOOLS = 12;
export const MAX_TOOL_CHARS = 40;

export interface CompatView {
    harnesses: string[];
    tools: string[];
}

export function compatView(item: CatalogItem | null): CompatView {
    const fm = (item?.fm ?? null) as Record<string, unknown> | null;
    const text = typeof fm?.compatibility === 'string' ? fm.compatibility.toLowerCase() : '';
    const harnesses = COMPAT_HARNESSES.filter((name) =>
        new RegExp(`(^|[^a-z0-9])${name}([^a-z0-9]|$)`).test(text),
    );
    const raw = Array.isArray(fm?.allowed_tools) ? (fm?.allowed_tools as unknown[]) : [];
    const tools = raw
        .filter((tool): tool is string => typeof tool === 'string' && tool.trim() !== '')
        .map((tool) => tool.trim().slice(0, MAX_TOOL_CHARS))
        .slice(0, MAX_TOOLS);
    return { harnesses: [...harnesses], tools };
}
