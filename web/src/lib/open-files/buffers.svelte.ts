import { repaintDrawer } from '../browser/drawer-repaint';
import type { OpenFileContent } from './api.svelte';

export interface FileBuffer {
    original: string;
    current: string;
    sha256: string;
    isExecutable: boolean;
    isSensitive: boolean;
    readOnly: boolean;
    revealed: boolean;
}

const buffers = $state<Record<string, FileBuffer>>({});

export function bufferOf(id: string): FileBuffer | null {
    return buffers[id] ?? null;
}

export function isDirty(id: string): boolean {
    const b = buffers[id];
    return !!b && b.current !== b.original;
}

export function anyDirty(): boolean {
    return Object.keys(buffers).some(isDirty);
}

export function loadBuffer(id: string, read: OpenFileContent): FileBuffer {
    const was = isDirty(id);
    const text = read.content ?? '';
    buffers[id] = {
        original: text, current: text, sha256: read.sha256 ?? '',
        isExecutable: !!read.is_executable, isSensitive: !!read.is_sensitive, readOnly: !!read.read_only,
        revealed: buffers[id]?.revealed ?? false,
    };
    if (was) repaintDrawer();
    return buffers[id];
}

export function setCurrent(id: string, text: string): void {
    const b = buffers[id];
    if (!b) return;
    const was = isDirty(id);
    b.current = text;
    if (was !== isDirty(id)) repaintDrawer();
}

export function markSaved(id: string, saved: string, sha256: string): void {
    const b = buffers[id];
    if (!b) return;
    const was = isDirty(id);
    b.original = saved;
    b.sha256 = sha256;
    if (was !== isDirty(id)) repaintDrawer();
}

export function reveal(id: string): void {
    const b = buffers[id];
    if (b) b.revealed = true;
}

export function dropBuffer(id: string): void {
    const was = isDirty(id);
    delete buffers[id];
    if (was) repaintDrawer();
}

export function bufferIds(): string[] {
    return Object.keys(buffers);
}

/* there is nothing */
export function moveBuffer(from: string, to: string): boolean {
    const b = buffers[from];
    if (!b || from === to || buffers[to]) return false;
    buffers[to] = b;
    delete buffers[from];
    repaintDrawer();
    return true;
}

export function guardUnload(target: Window | null = typeof window !== 'undefined' ? window : null): () => void {
    if (!target) return () => {};
    const onBeforeUnload = (event: BeforeUnloadEvent): void => {
        if (!anyDirty()) return;
        event.preventDefault();
        event.returnValue = '';
    };
    target.addEventListener('beforeunload', onBeforeUnload);
    return () => target.removeEventListener('beforeunload', onBeforeUnload);
}
