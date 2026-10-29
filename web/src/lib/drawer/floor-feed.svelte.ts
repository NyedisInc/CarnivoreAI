
export type FloorFeedRow = Readonly<Record<string, unknown>> & { readonly name: string };

let rows = $state.raw<readonly FloorFeedRow[]>([]);

export function publishFloorRows(next: readonly FloorFeedRow[]): void {
    rows = next;
}

export function floorFeedRows(): readonly FloorFeedRow[] {
    return rows;
}
