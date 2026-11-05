
export const THUMB_PX = 88;

const THUMB_QUALITY = 0.72;

export function drawThumb(img: HTMLImageElement): string | null {
  const w = img.naturalWidth || img.width || 0;
  const h = img.naturalHeight || img.height || 0;
  if (!w || !h) return null;
  const scale = Math.min(1, THUMB_PX / Math.max(w, h));
  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, Math.round(w * scale));
  canvas.height = Math.max(1, Math.round(h * scale));
  const ctx = typeof canvas.getContext === 'function' ? canvas.getContext('2d') : null;
  if (!ctx) return null;
  try {
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL('image/webp', THUMB_QUALITY);
  } catch (err) {
    console.warn('[AttachmentToast] thumbnail draw failed:', (err as Error | undefined)?.message);
    return null;
  }
}

export function attachmentPreviewDataUrl(blob: Blob | null | undefined): Promise<string | null> {
  return new Promise((resolve) => {
    if (!blob || typeof FileReader !== 'function' || typeof Image !== 'function' || typeof document === 'undefined') {
      resolve(null);
      return;
    }
    const reader = new FileReader();
    reader.onerror = () => resolve(null);
    reader.onload = () => {
      const img = new Image();
      img.onerror = () => resolve(null);
      img.onload = () => resolve(drawThumb(img));
      img.src = String(reader.result || '');
    };
    try {
      reader.readAsDataURL(blob);
    } catch (err) {
      console.warn('[AttachmentToast] preview unavailable:', (err as Error | undefined)?.message);
      resolve(null);
    }
  });
}
