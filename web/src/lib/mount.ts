import { mount, unmount, type Component } from 'svelte';

function findContainer(id: string): Element | null {
    if (typeof document === 'undefined' || typeof document.getElementById !== 'function') {
        return null;
    }
    return document.getElementById(id);
}

interface PanelRecord {
    target: Element;
    instance: Record<string, unknown>;
}

const panels = new Map<string, PanelRecord>();

export function mountPanel<Props extends Record<string, unknown>>(
    id: string,
    component: Component<Props, Record<string, unknown>>,
    props?: Props,
): Record<string, unknown> | null {
    const target = findContainer(id);
    if (!target) {
        console.warn('CloudeWeb.mountPanel: no element with id', id);
        unmountPanel(id);
        return null;
    }
    unmountPanel(id);
    const instance = mount(component, {
        target,
        props: (props ?? {}) as Props,
    }) as Record<string, unknown>;
    panels.set(id, { target, instance });
    return instance;
}

export function unmountPanel(id: string): boolean {
    const record = panels.get(id);
    if (!record) return false;
    panels.delete(id);
    unmount(record.instance, { outro: false });
    return true;
}

export function ensurePanel<Props extends Record<string, unknown>>(
    id: string,
    component: Component<Props, Record<string, unknown>>,
    props?: Props,
): Record<string, unknown> | null {
    const target = findContainer(id);
    const existing = panels.get(id);
    if (existing && target && existing.target === target) {
        return existing.instance;
    }
    return mountPanel(id, component, props);
}

export function panelInstance(id: string): Record<string, unknown> | null {
    return panels.get(id)?.instance ?? null;
}
