
interface GuideRow {
    section?: string;
    classes?: string[];
    classes_by_section?: Record<string, string[]>;
}

export interface PluginGuideEntries {
    rows: Record<string, GuideRow>;
    prose: Array<{ plugin: string; file: string; html: string }>;
}

const ROW_FILES = import.meta.glob('../cplugs/*/style-guide.json', { eager: true, import: 'default' }) as Record<string, { files?: Record<string, GuideRow> }>;
const PROSE_FILES = import.meta.glob('../cplugs/*/style-guide/*.html', { query: '?raw', eager: true, import: 'default' }) as Record<string, string>;

export function pluginGuideEntries(): PluginGuideEntries {
    const rows: Record<string, GuideRow> = {};
    for (const slice of Object.values(ROW_FILES)) Object.assign(rows, slice.files ?? {});
    const prose = Object.entries(PROSE_FILES)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([path, html]) => {
            const match = /cplugs\/([^/]+)\/style-guide\/([^/]+)$/.exec(path);
            return { plugin: match?.[1] ?? '', file: match?.[2] ?? '', html };
        });
    return { rows, prose };
}
