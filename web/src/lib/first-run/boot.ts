import './first-run.css';
import { ensurePanel, mountPanel, unmountPanel } from '../mount';
import FirstRun from './FirstRun.svelte';
import { decideEntry, type Entry } from './first-run-api';

export type MountEntry = 'first-run' | 'remote' | 'joined';

let mountedEntry: MountEntry | null = null;

let mountedId: string | null = null;

export interface CarnivoreFirstRun {
    probe(): Promise<Entry>;
    mount(containerId: string, entry: MountEntry): void;
    unmount(): void;
}

function mount(containerId: string, entry: MountEntry): void {
    if (mountedEntry === entry && mountedId === containerId) {
        ensurePanel(containerId, FirstRun, { entry });
        return;
    }
    if (mountedId !== null) unmountPanel(mountedId);
    const instance = mountPanel(containerId, FirstRun, { entry });
    mountedEntry = instance ? entry : null;
    mountedId = instance ? containerId : null;
}

function unmount(): void {
    if (mountedId !== null) unmountPanel(mountedId);
    mountedEntry = null;
    mountedId = null;
}

const surface: CarnivoreFirstRun = { probe: () => decideEntry(), mount, unmount };
(window as unknown as { CarnivoreFirstRun: CarnivoreFirstRun }).CarnivoreFirstRun = surface;
