import type { NotifyKind } from './contract.gen';

export interface CardMedia { id: string; mime?: string; bytes?: number; w?: number; h?: number; dur?: number }

/* there is nothing */
export function cardPictureUrl(kind: NotifyKind, media?: CardMedia | null, hasPoster = false): string | undefined {
    if (!media?.id || !/^[0-9a-f]{32}$/.test(media.id)) return undefined;
    if (kind === 'image') return `/api/v1/notifications/media/${media.id}`;
    if (kind === 'video' || (kind === 'file' && hasPoster)) return `/api/v1/notifications/media/${media.id}/poster`;
    return undefined;
}
