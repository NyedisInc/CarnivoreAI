import type { LensGroup, LensKey } from './lenses';

export interface RailState {
    lens: LensKey;
    counts: Readonly<Record<LensKey, number>>;
    groups: readonly LensGroup[];
    inactive: ReadonlySet<string>;
    current: string | null;
    listingDown: boolean;
    onLens: (key: LensKey) => void;
    onSection: (key: string) => void;
}
