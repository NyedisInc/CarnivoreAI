import { t } from '../i18n/index.svelte';
import { drawerEnv } from './env';
import * as GroupColor from './group-color';
import * as GroupStore from './group-store';
import { ledHtml } from '../sidebar-shell/project-header';
import { parseAttrs } from '../sidebar-shell/attr-string';
import { CHEVRON_PATH } from '../sidebar-shell/cascade-hint';
import { PREFIX, isExpanded, isOpenLayout, type LayoutRow } from './layouts-model';

export type LayoutMenuContext = {
    name: string; label: string; layoutUuid: string; sessionId: null; sessionUuid: null; projectId: null;
    surface: 'sidebar'; kind: 'layout'; owned: true; status: 'unknown'; unread: false; asleep: false; restartable: false;
    pluginItems: ''; groupable: true; groupUuid: string; renameable: true; renameReason: ''; forkable: false; forkReason: '';
    muted: false;
};

export function menuContext(row: LayoutRow, band?: string): LayoutMenuContext {
    let groupUuid = GroupStore.groupUuidOf(band || '');
    if (groupUuid && !GroupStore.groupByUuid(groupUuid)) groupUuid = null;
    return {
        name: row.name, label: row.label || '', layoutUuid: row.layout_uuid, sessionId: null, sessionUuid: null, projectId: null,
        surface: 'sidebar', kind: 'layout', owned: true, status: 'unknown', unread: false, asleep: false, restartable: false,
        pluginItems: '',
        groupable: true, groupUuid: groupUuid || '', renameable: true, renameReason: '', forkable: false, forkReason: '', muted: false,
    };
}

export interface LayoutRowParts {
    attrs: Record<string, string>;
    lightHtml: string;
    toggle: { attrs: Record<string, string>; svg: string } | null;
    icon: { attrs: Record<string, string>; svg: string } | null;
    name: { attrs: Record<string, string>; text: string; fxHtml: string };
    subtitle: string;
    pin: { name: string; pinned: boolean };
    menuContext: LayoutMenuContext;
}

const CHEVRON_HTML = '<span class="session-sidebar-group__chevron" aria-hidden="true">'
    + '<svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="2" '
    + `stroke-linecap="round" stroke-linejoin="round"><path d="${CHEVRON_PATH}"/></svg></span>`;

function toggleParts(uuid: string, expanded: boolean): NonNullable<LayoutRowParts['toggle']> {
    const chevron = CHEVRON_HTML;
    const verb = expanded ? t('layout.row.collapse') : t('layout.row.expand');
    return {
        attrs: {
            type: 'button', class: 'session-sidebar-layout__toggle', 'data-group-toggle': `${PREFIX}${uuid}`,
            'aria-expanded': expanded ? 'true' : 'false', 'aria-controls': `session-sidebar-layout-body-${uuid}`,
            title: verb, 'aria-label': verb,
        },
        svg: chevron,
    };
}

function iconParts(): LayoutRowParts['icon'] {
    const glyphs = drawerEnv().CloudeGlyphs as { glyphSvg?(id: string, size: number): string } | undefined;
    const svg = glyphs && typeof glyphs.glyphSvg === 'function' ? glyphs.glyphSvg('grid', 14) : '';
    return svg
        ? { attrs: { class: 'session-sidebar-row-provider', 'aria-hidden': 'true', title: t('layout.row.icon_label') }, svg }
        : null;
}

function lightHtml(row: LayoutRow, collapsed: boolean): string {
    return ledHtml((row._members || []) as Array<{ kind?: string }>, collapsed, true);
}

function rowAttrs(row: LayoutRow, band?: string): Record<string, string> {
    const active = isOpenLayout(row);
    return {
        class: 'session-sidebar-row',
        'data-name': row.name,
        ...parseAttrs(GroupColor.layoutRowAttrs(row)),
        ...(band ? { 'data-band': band, id: `session-sidebar-row__${row.name}__${band}` } : {}),
        'data-kind': 'layout',
        'data-layout-uuid': row.layout_uuid,
        'data-active': active ? '1' : '0',
        'data-pinned': row.is_pinned ? '1' : '0',
        'data-rename-state': 'renameable',
        draggable: 'true',
        role: 'option',
        'aria-selected': active ? 'true' : 'false',
        tabindex: '-1',
    };
}

export function rowParts(row: LayoutRow, band?: string): LayoutRowParts {
    const expandable = band === 'layouts';
    const expanded = expandable && isExpanded(row.layout_uuid);
    const title = row.label || row.name;
    return {
        attrs: rowAttrs(row, band),
        lightHtml: lightHtml(row, !expandable || !expanded),
        toggle: expandable ? toggleParts(row.layout_uuid, expanded) : null,
        icon: iconParts(),
        name: {
            attrs: { class: 'session-sidebar-row-name', 'data-row-name': row.name },
            text: title,
            fxHtml: GroupColor.layoutFxHtml(row, title),
        },
        subtitle: t('layout.row.members', { count: row.member_count || 0 }),
        pin: { name: row.name, pinned: !!row.is_pinned },
        menuContext: menuContext(row, band),
    };
}
