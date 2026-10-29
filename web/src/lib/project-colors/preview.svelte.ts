let state = $state<{ id: number; color: string } | null>(null);

export function projectColorPreview(projectId: number): string | undefined {
    return state && state.id === projectId ? state.color : undefined;
}

export function setProjectColorPreview(projectId: number, color: string | null): void {
    if (color) state = { id: projectId, color };
    else if (state && state.id === projectId) state = null;
}
