import { mountPanel } from '../mount';
import FavoriteChips from './FavoriteChips.svelte';
import { setFavoritesPayload, type payloadFromRow } from './favorites-store.svelte';

export const FAVORITES_CONTAINER_ID = 'common-commands-grid';

export interface SlashFavoritesProps extends Record<string, unknown> {
    onSelect: (command: string) => void;
    onChange: (payload: ReturnType<typeof payloadFromRow>) => void;
    describe: (command: string) => string;
}

export function mountSlashFavorites(props: SlashFavoritesProps): boolean {
    return mountPanel(FAVORITES_CONTAINER_ID, FavoriteChips as never, props) !== null;
}

export function setSlashFavorites(payload: unknown): void {
    setFavoritesPayload(payload);
}
