
import { toastSurface, type ToastManagerLike } from '../toast-surface';

export const WIDGETS_TOAST_KIND = 'WidgetsBars';

export type ToastKind = 'saved' | 'undone' | 'failed';

export interface ToastSpec {
    kind: ToastKind;
    text: string;
    surface: string;
    undo?: { label: string; run: () => void };
    ms?: number;
}

let shownId: string | null = null;
let timer: ReturnType<typeof setTimeout> | null = null;

function surface(): ToastManagerLike | null {
    const found = toastSurface();
    return found && typeof found.dismiss === 'function' ? found : null;
}

export function closeToast(): void {
    if (timer !== null) clearTimeout(timer);
    timer = null;
    if (shownId !== null) surface()?.dismiss?.(shownId, { syncToServer: false });
    shownId = null;
}

export function showToast(spec: ToastSpec): void {
    closeToast();
    const found = surface();
    if (!found) return;
    const id = `widgets-bars:${Date.now()}:${Math.random().toString(36).slice(2, 8)}`;
    found.add({
        id,
        session_id: null,
        kind: WIDGETS_TOAST_KIND,
        title: spec.text,
        body: null,
        session_label: spec.surface,
        local: true,
        ...(spec.kind === 'failed' ? { alert_severity: 'error' } : {}),
        ...(spec.undo ? { action_label: spec.undo.label, on_action: spec.undo.run } : {}),
    });
    shownId = id;
    timer = setTimeout(closeToast, spec.ms ?? 8000);
}
