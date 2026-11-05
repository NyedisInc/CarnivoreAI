import { fileById, type OpenFileInfo } from './api.svelte';
import { FILE_ROW_PREFIX } from './rows';

export function downloadRoute(id: string): string {
    return `/files/open/${encodeURIComponent(id)}/download`;
}

export function downloadableRow(name: string): OpenFileInfo | null {
    if (!name.startsWith(FILE_ROW_PREFIX)) return null;
    const row = fileById(name.slice(FILE_ROW_PREFIX.length));
    return row && row.kind === 'file' ? row : null;
}

const running = $state<Record<string, true>>({});

export function isDownloading(id: string): boolean {
    return running[id] === true;
}

export function isDownloadingRow(name: string): boolean {
    return name.startsWith(FILE_ROW_PREFIX) && isDownloading(name.slice(FILE_ROW_PREFIX.length));
}

export function setDownloading(id: string, on: boolean): void {
    if (on) running[id] = true;
    else delete running[id];
}
