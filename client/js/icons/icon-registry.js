
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
    { id: 'logo-pi', glyph: 'logo-pi', label: 'icon.logo_pi', keywords: ['logo', 'agent', 'cli'] },
    { id: 'logo-copilot', glyph: 'logo-copilot', label: 'icon.logo_copilot', keywords: ['logo', 'agent', 'cli'] },
    { id: 'logo-devin', glyph: 'logo-devin', label: 'icon.logo_devin', keywords: ['logo', 'agent', 'cli'] },
    { id: 'logo-kimi', glyph: 'logo-kimi', label: 'icon.logo_kimi', keywords: ['logo', 'agent', 'cli'] },
    { id: 'logo-opencode', glyph: 'logo-opencode', label: 'icon.logo_opencode', keywords: ['logo', 'agent', 'cli'] },
    { id: 'logo-kilo', glyph: 'logo-kilo', label: 'icon.logo_kilo', keywords: ['logo', 'agent', 'cli'] },
    { id: 'logo-qoder', glyph: 'logo-qoder', label: 'icon.logo_qoder', keywords: ['logo', 'agent', 'cli'] },
    { id: 'logo-qwen', glyph: 'logo-qwen', label: 'icon.logo_qwen', keywords: ['logo', 'agent', 'cli'] },
    { id: 'logo-cursor', glyph: 'logo-cursor', label: 'icon.logo_cursor', keywords: ['logo', 'agent', 'cli'] },
    { id: 'logo-mastra', glyph: 'logo-mastra', label: 'icon.logo_mastra', keywords: ['logo', 'agent', 'cli'] },
    { id: 'logo-antigravity', glyph: 'logo-antigravity', label: 'icon.logo_antigravity', keywords: ['logo', 'agent', 'cli'] },
    { id: 'logo-grok', glyph: 'logo-grok', label: 'icon.logo_grok', keywords: ['logo', 'agent', 'cli'] },
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

export function iconSvg(id, size) {
    const entry = findIcon(id);
    if (!entry || !GLYPHS[entry.glyph]) return '';
    return glyphSvg(entry.glyph, size);
}
