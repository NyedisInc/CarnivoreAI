import { checkHeroImage, MAX_IMAGE_BYTES, readBytes, type HeroCheck } from '../catalog/card-image';

export { checkHeroImage, type HeroCheck };

export async function checkHeroFile(file: Blob): Promise<HeroCheck> {
    const bytes = file.size > MAX_IMAGE_BYTES ? new Uint8Array(0) : await readBytes(file).catch(() => new Uint8Array(0));
    return checkHeroImage(bytes, file.size);
}

export async function opensAsImage(url: string): Promise<boolean> {
    const probe = new Image();
    if (typeof probe.decode !== 'function') return true;
    probe.src = url;
    try {
        await probe.decode();
        return true;
    } catch {
        return false;
    }
}
