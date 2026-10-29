import { mount, unmount, type Component } from 'svelte';

export interface Closable<Result> {
    close(value: Result | null): void;
}

let openCount = 0;

export function openModal<Result, Props extends Record<string, unknown>>(
    component: Component<Props & Closable<Result>, Record<string, unknown>>,
    props?: Props,
): Promise<Result | null> {
    return new Promise<Result | null>((resolve) => {
        const host = document.createElement('div');
        document.body.appendChild(host);
        openCount += 1;

        let settled = false;
        let instance: Record<string, unknown> | null = null;

        const finish = (value: Result | null): void => {
            if (settled) return;
            settled = true;
            openCount -= 1;
            if (instance) unmount(instance, { outro: false });
            if (host.parentNode) host.parentNode.removeChild(host);
            resolve(value);
        };

        try {
            instance = mount(component, {
                target: host,
                props: { ...(props ?? {}), close: finish } as Props & Closable<Result>,
            }) as Record<string, unknown>;
        } catch (error) {
            console.error('CloudeWeb.openModal: the modal failed to mount', error);
            finish(null);
        }
    });
}

export function openModalCount(): number {
    return openCount;
}
