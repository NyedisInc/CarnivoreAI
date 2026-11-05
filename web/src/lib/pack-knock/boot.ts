import { mountInto } from '../mount';
import PackKnock from './PackKnock.svelte';

let host: HTMLElement | null = null;

export function bootPackKnock(): void {
    if (host) return;
    host = document.createElement('div');
    host.id = 'pack-knock-host';
    document.body.appendChild(host);
    mountInto(host, PackKnock);
}
