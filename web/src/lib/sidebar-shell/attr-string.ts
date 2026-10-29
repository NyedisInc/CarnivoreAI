
export function parseAttrs(attrs: string): Record<string, string> {
    const out: Record<string, string> = {};
    const decode = (v: string): string => v
        .replace(/&quot;/g, '"').replace(/&#39;/g, "'")
        .replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&amp;/g, '&');
    for (const m of (attrs || '').matchAll(/([\w:-]+)="([^"]*)"/g)) {
        out[m[1] as string] = decode(m[2] as string);
    }
    return out;
}
