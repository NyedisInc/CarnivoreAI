import { cardView } from '../catalog/card';
import { sortCards } from '../catalog/sort';
import type { CatalogItem } from '../catalog/types';

export function listedCatalogPlugins(items: readonly CatalogItem[], installedIds: ReadonlySet<string>): CatalogItem[] {
    return items.filter((item) => !(cardView(item, false).isCplug && installedIds.has(item.id as string)));
}

export function warezOrder(items: readonly CatalogItem[]): CatalogItem[] {
    const byId = new Map(items.map((item) => [item.id as string, item] as const));
    return sortCards(items.map((item) => cardView(item, false)), 'featured', items).flatMap((card) => (card.id && byId.has(card.id) ? [byId.get(card.id) as CatalogItem] : []));
}
