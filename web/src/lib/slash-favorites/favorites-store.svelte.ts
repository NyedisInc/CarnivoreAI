import { rowFromPayload, type Favorite, type FavoritesRow } from './favorites-model';

export const favoritesState = $state<{ row: FavoritesRow }>({
    row: { favorites: [], defaulted: false },
});

export function setFavoritesPayload(payload: unknown): void {
    favoritesState.row = rowFromPayload(payload);
}

export function setFavoritesRow(row: FavoritesRow): void {
    favoritesState.row = row;
}

export function payloadFromRow(row: FavoritesRow): {
    commands: string[];
    command_details: Favorite[];
    defaulted: boolean;
} {
    return {
        commands: row.favorites.map((f) => f.command),
        command_details: row.favorites.map((f) => ({ ...f })),
        defaulted: row.defaulted,
    };
}
