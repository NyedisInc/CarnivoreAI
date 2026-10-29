import type { Translate } from '../sessions/types';
import type { ActiveKeys, Census } from './query';

export interface MenuItem {
    key: string;
    label: string;
    count?: number;
    frac?: number;
}

export interface MenuPanel {
    id: 'files' | 'state' | 'sort' | 'board';
    title: string;
    items: MenuItem[];
    on: string | null;
}

export interface MenuCounts {
    census: Census;
    on: ActiveKeys;
}

export function buildPanels(c: MenuCounts, t: Translate): MenuPanel[] {
    const all = c.census.total || 1;
    const item = (key: string, id: string, n?: number): MenuItem => ({ key, label: t(`warez.elite.item.${id}`), ...(n == null ? {} : { count: n, frac: n / all }) });
    const f = c.census.files;
    const s = c.census.state;
    return [
        { id: 'files', title: t('warez.elite.panel.files'), on: c.on.files, items: [item('a', 'all', f.a), item('s', 'skills', f.s), item('t', 'themes', f.t), item('m', 'mods', f.m), item('p', 'plugins', f.p)] },
        { id: 'state', title: t('warez.elite.panel.state'), on: c.on.state, items: [item('i', 'installed', s.i), item('v', 'available', s.v), item('u', 'updates', s.u), item('n', 'new', s.n)] },
        { id: 'sort', title: t('warez.elite.panel.sort'), on: c.on.sort, items: [item('f', 'featured'), item('w', 'newest'), item('o', 'oldest'), item('e', 'name'), item('d', 'downloaded'), item('c', 'updated')] },
        { id: 'board', title: t('warez.elite.panel.board'), on: c.on.board, items: [item('/', 'search'), item('r', 'refresh'), item('l', 'top'), item('b', 'publish'), item('?', 'help'), item('g', 'goodbye')] },
    ];
}

export function comboOf(key: string): string {
    if (key === '/') return 'Slash';
    if (key === '?') return 'shift+Slash';
    return /^[a-z]$/i.test(key) ? `Key${key.toUpperCase()}` : key;
}
