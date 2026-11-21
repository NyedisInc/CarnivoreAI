
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
    { id: 'briefcase', glyph: 'briefcase', label: 'icon.briefcase', keywords: ['work','job','office'] },
    { id: 'money', glyph: 'money', label: 'icon.money', keywords: ['finance','cash','budget','dollar'] },
    { id: 'health', glyph: 'health', label: 'icon.health', keywords: ['medical','care','cross'] },
    { id: 'heart', glyph: 'heart', label: 'icon.heart', keywords: ['love','favorite','health'] },
    { id: 'plane', glyph: 'plane', label: 'icon.plane', keywords: ['travel','flight','trip'] },
    { id: 'music', glyph: 'music', label: 'icon.music', keywords: ['audio','song','note'] },
    { id: 'video', glyph: 'video', label: 'icon.video', keywords: ['film','movie','camera'] },
    { id: 'photo', glyph: 'photo', label: 'icon.photo', keywords: ['image','picture','gallery'] },
    { id: 'book', glyph: 'book', label: 'icon.book', keywords: ['read','docs','library'] },
    { id: 'school', glyph: 'school', label: 'icon.school', keywords: ['learn','study','education','class'] },
    { id: 'cart', glyph: 'cart', label: 'icon.cart', keywords: ['shopping','shop','store','buy'] },
    { id: 'mail', glyph: 'mail', label: 'icon.mail', keywords: ['email','inbox','message','letter'] },
    { id: 'phone', glyph: 'phone', label: 'icon.phone', keywords: ['call','mobile','contact'] },
    { id: 'calendar', glyph: 'calendar', label: 'icon.calendar', keywords: ['date','plan','events'] },
    { id: 'map-pin', glyph: 'map-pin', label: 'icon.map_pin', keywords: ['location','place','map','address'] },
    { id: 'server', glyph: 'server', label: 'icon.server', keywords: ['host','machine','infra'] },
    { id: 'lock', glyph: 'lock', label: 'icon.lock', keywords: ['secure','private','password'] },
    { id: 'key', glyph: 'key', label: 'icon.key', keywords: ['access','secret','credential'] },
    { id: 'shield', glyph: 'shield', label: 'icon.shield', keywords: ['security','protect','safe'] },
    { id: 'bug', glyph: 'bug', label: 'icon.bug', keywords: ['issue','defect','debug'] },
    { id: 'rocket', glyph: 'rocket', label: 'icon.rocket', keywords: ['launch','ship','startup'] },
    { id: 'lightbulb', glyph: 'lightbulb', label: 'icon.lightbulb', keywords: ['idea','tip','light'] },
    { id: 'flag', glyph: 'flag', label: 'icon.flag', keywords: ['milestone','mark','goal'] },
    { id: 'gift', glyph: 'gift', label: 'icon.gift', keywords: ['present','reward','birthday'] },
    { id: 'car', glyph: 'car', label: 'icon.car', keywords: ['drive','auto','vehicle'] },
    { id: 'gamepad', glyph: 'gamepad', label: 'icon.gamepad', keywords: ['game','play','controller','fun'] },
    { id: 'paint-brush', glyph: 'paint-brush', label: 'icon.paint_brush', keywords: ['art','design','draw','paint'] },
    { id: 'leaf', glyph: 'leaf', label: 'icon.leaf', keywords: ['nature','plant','green','eco'] },
    { id: 'trophy', glyph: 'trophy', label: 'icon.trophy', keywords: ['win','award','goal'] },
    { id: 'target', glyph: 'target', label: 'icon.target', keywords: ['goal','aim','focus'] },
    { id: 'flame', glyph: 'flame', label: 'icon.flame', keywords: ['hot','fire','urgent'] },
    { id: 'tag', glyph: 'tag', label: 'icon.tag', keywords: ['label','price','category'] },
    { id: 'headphones', glyph: 'headphones', label: 'icon.headphones', keywords: ['audio','listen','podcast'] },
    { id: 'compass', glyph: 'compass', label: 'icon.compass', keywords: ['explore','navigate','direction'] },
    { id: 'sun', glyph: 'sun', label: 'icon.sun', keywords: ['day','light','morning'] },
    { id: 'moon', glyph: 'moon', label: 'icon.moon', keywords: ['night','dark','sleep'] },
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
