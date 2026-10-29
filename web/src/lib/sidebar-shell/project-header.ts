import { drawerEnv } from '../drawer/env';
import { headingMark } from '../drawer/group-icon';
import { groupUuidOf } from '../drawer/group-store';
import { pageSectionMeta } from '../drawer/page-sections';

interface LightRow { kind?: string }

interface HeaderGlobals {
    SessionStatusSummary?: { summaryHtml(rows: unknown[]): string };
    CloudeGlyphs?: { glyphSvg?(name: string, size: number): string };
}

const HEADING_GLYPH_PX = 12;

export function ledHtml(rows: LightRow[], collapsed: boolean, showLight?: boolean): string {
    if (!collapsed || showLight === false) return '';
    const summary = (drawerEnv() as HeaderGlobals).SessionStatusSummary;
    const led = rows && rows.some((r) => r.kind !== 'browser') && summary ? summary.summaryHtml(rows) : '';
    return led ? `<span class="session-sidebar-group__project-led">${led}</span>` : '';
}

export function iconHtml(name: string | null): string {
    if (!name) return '';
    const glyphs = (drawerEnv() as HeaderGlobals).CloudeGlyphs;
    const svg = glyphs && typeof glyphs.glyphSvg === 'function' ? glyphs.glyphSvg(name, HEADING_GLYPH_PX) : '';
    return svg ? `<span class="session-sidebar-group__icon" aria-hidden="true">${svg}</span>` : '';
}

const BAND_GLYPHS: Readonly<Record<string, string>> = {
    pinned: 'pin', open: 'bolt', sleeping: 'sleeping-agent', terminals: 'terminal', browsers: 'globe', files: 'code',
};

export function iconForBand(key: string, isProject?: boolean): string | null {
    if (isProject) return 'folder';
    const fixed = BAND_GLYPHS[key];
    if (fixed) return fixed;
    const sectionIcon = pageSectionMeta(key)?.icon ?? null;
    if (sectionIcon) return sectionIcon;
    return key === 'layouts' ? 'grid' : null;
}

export function pickedIconHtml(o: { key: string; bandKind: string }): string {
    if (o.bandKind !== 'group') return '';
    return headingMark(groupUuidOf(o.key));
}
