import { mountPanel, unmountPanel } from '../mount';
import { hostDocument } from '../sessions/env';
import { t } from '../i18n/index.svelte';
import MediaLightbox from '../help/MediaLightbox.svelte';

export const ATTACHMENT_LIGHTBOX_ID = 'attachment-lightbox';

let liveUrl: string | null = null;

export function closeAttachmentLightbox(): boolean {
    const was = unmountPanel(ATTACHMENT_LIGHTBOX_ID);
    if (liveUrl) {
        URL.revokeObjectURL(liveUrl);
        liveUrl = null;
    }
    return was;
}

export function openAttachmentLightbox(
    blob: Blob,
    name: string,
    returnFocus?: HTMLElement | null,
): boolean {
    const doc = hostDocument();
    if (!doc || !blob) return false;
    closeAttachmentLightbox();
    let host = doc.getElementById(ATTACHMENT_LIGHTBOX_ID);
    if (!host) {
        host = doc.createElement('div');
        host.id = ATTACHMENT_LIGHTBOX_ID;
        doc.body.appendChild(host);
    }
    returnFocus?.focus();
    liveUrl = URL.createObjectURL(blob);
    const mounted = mountPanel(ATTACHMENT_LIGHTBOX_ID, MediaLightbox, {
        src: liveUrl,
        alt: name || t('toast.attachment.preview_alt'),
        caption: name || undefined,
        onClose: () => void closeAttachmentLightbox(),
    });
    if (mounted === null) closeAttachmentLightbox();
    return mounted !== null;
}
