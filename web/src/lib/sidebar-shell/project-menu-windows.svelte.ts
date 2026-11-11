import { mountInto } from '../mount';
import ProjectMenuWindows from './ProjectMenuWindows.svelte';
import type { ProjectTool } from '../sessions-page/project-tools';

export const projectWindows = $state<{ migrate: boolean; tool: { tool: ProjectTool; project: { id: number; name: string } } | null }>({ migrate: false, tool: null });

let host: HTMLElement | null = null;
let stopHost: (() => void) | null = null;

function ensureHost(): void {
    if (host?.isConnected && stopHost) return;
    stopHost?.();
    host = document.createElement('div');
    host.id = 'project-menu-windows';
    document.body.appendChild(host);
    stopHost = mountInto(host, ProjectMenuWindows, {});
}

export function openDrawerProjectTool(tool: ProjectTool, project: { id: number; name: string }): void {
    ensureHost();
    projectWindows.tool = { tool, project };
}

export function wantDrawerMigrate(): void {
    if (document.querySelector('.sp-body')) return;
    ensureHost();
    projectWindows.migrate = true;
}
