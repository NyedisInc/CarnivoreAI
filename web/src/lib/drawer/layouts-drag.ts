import { bridge } from './layouts-model';

let draggingUuid: string | null = null;
let wired = false;

function layoutRow(target: EventTarget | null): HTMLElement | null {
    const el = target as Element | null;
    return el && typeof el.closest === 'function' ? el.closest<HTMLElement>('[data-kind="layout"]') : null;
}

export function reorderedUuids(current: string[], moving: string, over: string, before: boolean): string[] {
    const order = current.filter((u) => u !== moving);
    const at = order.indexOf(over);
    const insertAt = before ? at : at + 1;
    order.splice(insertAt < 0 ? order.length : insertAt, 0, moving);
    return order;
}

async function onDrop(e: DragEvent): Promise<void> {
    if (!draggingUuid) return;
    const target = layoutRow(e.target);
    draggingUuid = null;
    if (!target) return;
    e.preventDefault();
    const overUuid = target.dataset.layoutUuid;
    const moving = (e.dataTransfer ? e.dataTransfer.getData('text/plain') : null) || null;
    if (!moving || !overUuid || moving === overUuid) return;
    const box = target.getBoundingClientRect();
    const b = bridge();
    if (!b || typeof b.reorder !== 'function') return;
    const order = reorderedUuids(b.list().map((L) => L.layout_uuid), moving, overUuid, e.clientY < box.top + box.height / 2);
    try {
        await b.reorder(order);
    } catch (err) {
        console.error('SessionSidebarLayouts: reorder failed:', err);
    }
}

export function wireLayoutsDrag(): void {
    if (wired) return;
    if (typeof document === 'undefined' || typeof document.addEventListener !== 'function') return;
    wired = true;
    document.addEventListener('dragstart', (e) => {
        const row = layoutRow(e.target);
        if (!row) return;
        draggingUuid = row.dataset.layoutUuid || null;
        if (e.dataTransfer) {
            e.dataTransfer.effectAllowed = 'move';
            try { e.dataTransfer.setData('text/plain', draggingUuid || ''); } catch {  }
        }
    });
    document.addEventListener('dragover', (e) => {
        if (draggingUuid && layoutRow(e.target)) e.preventDefault();
    });
    document.addEventListener('drop', (e) => { void onDrop(e); });
    document.addEventListener('dragend', () => { draggingUuid = null; });
}
