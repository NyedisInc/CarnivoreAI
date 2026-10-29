/* and writes nothing */
import * as G from '../drawer/group-store';
import {
    isSectionId, moveSection, resolveSectionOrder, setPreviewOrder, stepSection, type SectionId,
} from '../drawer/section-order';
import { current as arrangement, saveSectionOrder } from '../drawer/store';
import { t } from '../i18n/index.svelte';
import { writeGroupOrder } from './heading-group-actions';
import { announce } from './interaction-globals';
import { closestTo, drawer, listElement } from './row-globals';
import { slop } from './row-drag';

const SECTION_ATTR = 'data-section';

const MEMBER_ATTR = 'data-group';

const DRAGGING_CLASS = 'session-sidebar-list--section-dragging';
const LIFTED_ATTR = 'data-section-lifted';

const NOT_A_HANDLE = '.session-sidebar-rename-edit, [data-group-menu], [data-project-menu], [data-company-menu], input, textarea';

const TOUCH_GRIP = '.session-sidebar-group__icon, .session-sidebar-group__gutter';

interface Drag {
    id: SectionId;
    el: HTMLElement;
    groupUuid: string | null;
    base: SectionId[];
    visible: SectionId[];
    baseGroups: string[];
    nextSections: SectionId[] | null;
    nextGroups: string[] | null;
    startX: number;
    startY: number;
    active: boolean;
    cancelled: boolean;
    pointerId: number;
    pointerType: string;
    painted: string;
}

let drag: Drag | null = null;

let claimedClick = false;

export function isDragging(): boolean {
    return !!drag && drag.active;
}

export function sectionDragTookClick(): boolean {
    const was = claimedClick;
    claimedClick = false;
    return was;
}

function wrappers(list: Element): HTMLElement[] {
    return Array.from(list.querySelectorAll<HTMLElement>(`[${SECTION_ATTR}]`));
}

function memberWrappers(list: Element): HTMLElement[] {
    return Array.from(list.querySelectorAll<HTMLElement>(`[${MEMBER_ATTR}^="g:"]`));
}

function visibleSections(list: Element): SectionId[] {
    const out: SectionId[] = [];
    for (const el of wrappers(list)) {
        const id = el.getAttribute(SECTION_ATTR);
        if (isSectionId(id) && out.indexOf(id) === -1) out.push(id);
    }
    return out;
}

function headingOf(el: Element): Element | null {
    const first = el.firstElementChild;
    return first && first.classList.contains('session-sidebar-group__headerrow') ? first : null;
}

function headingMid(el: Element): number {
    const box = (headingOf(el) ?? el).getBoundingClientRect();
    return box.top + box.height / 2;
}

function labelOf(el: Element): string {
    return headingOf(el)?.querySelector('.session-sidebar-group__label')?.textContent?.trim() || el.getAttribute(SECTION_ATTR) || '';
}

function sectionWrapper(row: Element): HTMLElement | null {
    const parent = row.parentElement;
    return parent && parent.hasAttribute(SECTION_ATTR) && parent.firstElementChild === row ? parent : null;
}

function memberWrapper(row: Element): HTMLElement | null {
    const parent = row.parentElement;
    return parent && parent.firstElementChild === row && G.groupUuidOf(parent.getAttribute(MEMBER_ATTR)) ? parent : null;
}

export function onSectionPointerDown(e: PointerEvent, row: Element): void {
    claimedClick = false;
    if (drag) return;
    if (typeof e.button === 'number' && e.button !== 0) return;
    const member = memberWrapper(row);
    const wrap = member ?? sectionWrapper(row);
    const list = listElement();
    if (!wrap || !list || !list.contains(wrap)) return;
    if (closestTo(e.target, NOT_A_HANDLE)) return;
    const grip = closestTo(e.target, TOUCH_GRIP);
    if (e.pointerType === 'touch' && !grip) return;
    const id = member ? 'groups' : wrap.getAttribute(SECTION_ATTR);
    if (!isSectionId(id)) return;
    drag = {
        id,
        el: wrap,
        groupUuid: member ? G.groupUuidOf(member.getAttribute(MEMBER_ATTR)) : null,
        base: resolveSectionOrder(arrangement().sections),
        visible: visibleSections(list),
        baseGroups: G.current().groups.map((g) => g.group_uuid),
        nextSections: null,
        nextGroups: null,
        startX: e.clientX,
        startY: e.clientY,
        active: false,
        cancelled: false,
        pointerId: e.pointerId,
        pointerType: e.pointerType,
        painted: '',
    };
    try {
        (grip ?? row).setPointerCapture?.(e.pointerId);
    } catch {
    }
    document.addEventListener('pointermove', onPointerMove);
    document.addEventListener('pointerup', onPointerUp);
    document.addEventListener('pointercancel', onPointerCancel);
    document.addEventListener('keydown', onEscape, true);
}

function repaint(): void {
    drawer()?.repaint?.();
}

function place(d: Drag, list: Element, clientY: number): void {
    let key: string;
    if (d.groupUuid !== null) {
        const others = memberWrappers(list).filter((el) => el !== d.el);
        const before = others.find((el) => clientY < headingMid(el));
        const beforeUuid = before ? G.groupUuidOf(before.getAttribute(MEMBER_ATTR)) : null;
        const rest = d.baseGroups.filter((u) => u !== d.groupUuid);
        const at = beforeUuid ? rest.indexOf(beforeUuid) : -1;
        const next = at === -1 ? [...rest, d.groupUuid as string] : [...rest.slice(0, at), d.groupUuid as string, ...rest.slice(at)];
        d.nextGroups = next;
        d.nextSections = null;
        key = `g:${next.join(',')}`;
        if (key === d.painted) return;
        d.painted = key;
        setPreviewOrder(null);
        G.previewGroupOrder(next);
    } else {
        const others = wrappers(list).filter((el) => el.getAttribute(SECTION_ATTR) !== d.id);
        const before = others.find((el) => clientY < headingMid(el));
        const beforeId = before ? before.getAttribute(SECTION_ATTR) : null;
        const next = moveSection(d.base, d.id, isSectionId(beforeId) ? beforeId : null, d.visible);
        d.nextSections = next;
        d.nextGroups = null;
        key = `s:${next.join(',')}`;
        if (key === d.painted) return;
        d.painted = key;
        G.previewGroupOrder(null);
        setPreviewOrder(next);
    }
    repaint();
}

function onPointerMove(e: PointerEvent): void {
    const d = drag;
    const list = listElement();
    if (!d || !list || e.pointerId !== d.pointerId) return;
    if (!d.active) {
        if (Math.hypot(e.clientX - d.startX, e.clientY - d.startY) < slop(d.pointerType)) return;
        d.active = true;
        window.getSelection?.()?.removeAllRanges?.();
        list.classList.add(DRAGGING_CLASS);
        d.el.setAttribute(LIFTED_ATTR, '1');
    }
    if (e.cancelable) e.preventDefault();
    place(d, list, e.clientY);
}

/* and writes nothing */
function onEscape(e: KeyboardEvent): void {
    if (e.key !== 'Escape' || !drag || !drag.active) return;
    e.preventDefault();
    e.stopPropagation();
    drag.cancelled = true;
    finish();
}

function onPointerCancel(): void {
    if (drag) drag.cancelled = true;
    finish();
}

function onPointerUp(): void {
    finish();
}

function finish(): void {
    const d = drag;
    if (!d) return;
    drag = null;
    document.removeEventListener('pointermove', onPointerMove);
    document.removeEventListener('pointerup', onPointerUp);
    document.removeEventListener('pointercancel', onPointerCancel);
    document.removeEventListener('keydown', onEscape, true);
    claimedClick = d.active;
    const list = listElement();
    list?.classList.remove(DRAGGING_CLASS);
    d.el.removeAttribute(LIFTED_ATTR);
    if (!d.active) return;
    const name = labelOf(d.el);
    const sections = d.nextSections;
    const groups = d.nextGroups;
    if (!d.cancelled && groups && groups.join() !== d.baseGroups.join()) {
        void writeGroupOrder(groups).then((ok) => {
            G.previewGroupOrder(null);
            repaint();
            if (ok) announce(t('sidebar.group.moved', { position: groups.indexOf(d.groupUuid as string) + 1, total: groups.length }));
        });
        return;
    }
    setPreviewOrder(null);
    G.previewGroupOrder(null);
    if (!d.cancelled && sections && sections.join() !== d.base.join()) {
        saveSectionOrder(sections);
        const shown = sections.filter((x) => d.visible.indexOf(x) !== -1);
        announce(t('sidebar.row.move.moved', { name, position: shown.indexOf(d.id) + 1, total: shown.length }));
    }
    repaint();
}

function focusHeading(key: string): void {
    const list = listElement();
    const button = list?.querySelector<HTMLElement>(`[data-group-toggle="${key}"]`);
    button?.focus();
}

export function onSectionKeydown(e: KeyboardEvent, row: Element): boolean {
    if (!e.altKey || (e.key !== 'ArrowUp' && e.key !== 'ArrowDown')) return false;
    const member = memberWrapper(row);
    const wrap = member ?? sectionWrapper(row);
    const list = listElement();
    const id = member ? 'groups' : wrap?.getAttribute(SECTION_ATTR);
    if (!wrap || !list || !isSectionId(id)) return false;
    e.preventDefault();
    e.stopPropagation();
    const delta = e.key === 'ArrowUp' ? -1 : 1;
    const key = row.querySelector('[data-group-toggle]')?.getAttribute('data-group-toggle') || '';
    const name = labelOf(wrap);
    const uuid = member ? G.groupUuidOf(member.getAttribute(MEMBER_ATTR)) : null;
    if (uuid) {
        const order = G.current().groups.map((g) => g.group_uuid);
        const at = order.indexOf(uuid);
        if (at === -1 || at + delta < 0 || at + delta >= order.length) {
            announce(t(delta < 0 ? 'sidebar.row.move.top_of_list' : 'sidebar.row.move.bottom_of_list', { name }));
            return true;
        }
        const next = order.slice();
        next[at] = order[at + delta] as string;
        next[at + delta] = uuid;
        void writeGroupOrder(next).then((ok) => {
            if (ok) announce(t('sidebar.group.moved', { position: at + delta + 1, total: order.length }));
            focusHeading(key);
        });
        return true;
    }
    const order = resolveSectionOrder(arrangement().sections);
    const visible = visibleSections(list);
    const next = stepSection(order, visible, id, delta);
    if (!next) {
        announce(t(delta < 0 ? 'sidebar.row.move.top_of_list' : 'sidebar.row.move.bottom_of_list', { name }));
        return true;
    }
    saveSectionOrder(next);
    repaint();
    focusHeading(key);
    const shown = next.filter((x) => visible.indexOf(x) !== -1);
    announce(t('sidebar.row.move.moved', { name, position: shown.indexOf(id) + 1, total: shown.length }));
    return true;
}
