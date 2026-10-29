
import { GLYPHS, glyphSvg } from './glyphs.js';


export const ICON_REGISTRY = Object.freeze([
    { id: 'folder', glyph: 'folder', label: 'icon.folder', keywords: ['project', 'directory'] },
    { id: 'folder-tree', glyph: 'folder-tree', label: 'icon.folder_tree', keywords: ['projects', 'files'] },
    { id: 'terminal', glyph: 'terminal', label: 'icon.terminal', keywords: ['shell', 'console', 'prompt'] },
    { id: 'code', glyph: 'code', label: 'icon.code', keywords: ['brackets', 'source', 'dev'] },
    { id: 'globe', glyph: 'globe', label: 'icon.globe', keywords: ['web', 'browser', 'world'] },
    { id: 'home', glyph: 'home', label: 'icon.home', keywords: ['house', 'main'] },
    { id: 'grid', glyph: 'grid', label: 'icon.grid', keywords: ['layout', 'panes'] },
    { id: 'cube', glyph: 'cube', label: 'icon.cube', keywords: ['box', 'package', 'plugin'] },
    { id: 'wrench', glyph: 'wrench', label: 'icon.wrench', keywords: ['tool', 'fix', 'skill'] },
    { id: 'flask', glyph: 'flask', label: 'icon.flask', keywords: ['lab', 'experiment', 'test'] },
    { id: 'telescope', glyph: 'telescope', label: 'icon.telescope', keywords: ['watch', 'research', 'look'] },
    { id: 'database', glyph: 'database', label: 'icon.database', keywords: ['data', 'storage', 'db'] },
    { id: 'cloud', glyph: 'cloud', label: 'icon.cloud', keywords: ['server', 'remote', 'deploy'] },
    { id: 'chart', glyph: 'chart', label: 'icon.chart', keywords: ['stats', 'bars', 'metrics'] },
    { id: 'chat', glyph: 'chat', label: 'icon.chat', keywords: ['message', 'talk', 'bubble'] },
    { id: 'users', glyph: 'users', label: 'icon.users', keywords: ['team', 'people', 'group'] },
    { id: 'bell', glyph: 'bell', label: 'icon.bell', keywords: ['alert', 'notify'] },
    { id: 'clock', glyph: 'clock', label: 'icon.clock', keywords: ['time', 'schedule'] },
    { id: 'link', glyph: 'link', label: 'icon.link', keywords: ['chain', 'url'] },
    { id: 'pin', glyph: 'pin', label: 'icon.pin', keywords: ['pushpin', 'keep'] },
    { id: 'star', glyph: 'star', label: 'icon.star', keywords: ['favorite', 'important'] },
    { id: 'crown', glyph: 'crown', label: 'icon.crown', keywords: ['king', 'leader', 'master'] },
    { id: 'bolt', glyph: 'bolt', label: 'icon.bolt', keywords: ['lightning', 'fast', 'power'] },
    { id: 'spark', glyph: 'spark', label: 'icon.spark', keywords: ['sparkle', 'new', 'ai'] },
    { id: 'coffee', glyph: 'coffee', label: 'icon.coffee', keywords: ['cup', 'break'] },
]);

export const RETIRED_ICON_IDS = Object.freeze({});

export function findIcon(id) {
    if (typeof id !== 'string' || id === '') return null;
    const current = Object.prototype.hasOwnProperty.call(RETIRED_ICON_IDS, id)
        ? RETIRED_ICON_IDS[id]
        : id;
    for (const entry of ICON_REGISTRY) {
        if (entry.id === current) return entry;
    }
    return null;
}

/* width="12" */
export function iconSvg(id, size) {
    const entry = findIcon(id);
    if (!entry || !GLYPHS[entry.glyph]) return '';
    return glyphSvg(entry.glyph, size);
}
