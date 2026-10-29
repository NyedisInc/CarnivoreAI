import { MAX_IMAGE_BYTES } from '../catalog/card-image';
import { HERO_H, HERO_W } from './hero-art';

export type RasterType = 'image/png' | 'image/webp';

export type Encoder = (width: number, height: number, type: RasterType) => Promise<Blob | null>;

export interface MadeHero { blob: Blob; type: RasterType; width: number; height: number }

const STEPS: readonly { type: RasterType; width: number; height: number }[] = [
    { type: 'image/png', width: HERO_W, height: HERO_H },
    { type: 'image/webp', width: HERO_W, height: HERO_H },
    { type: 'image/png', width: 1200, height: 800 },
];

export async function rasterLadder(encode: Encoder, limit: number = MAX_IMAGE_BYTES): Promise<MadeHero | null> {
    for (const step of STEPS) {
        const blob = await encode(step.width, step.height, step.type);
        if (blob && blob.type === step.type && blob.size <= limit) return { blob, ...step };
    }
    return null;
}

export function canvasEncoder(svg: string): Encoder {
    return async (width, height, type) => {
        const url = URL.createObjectURL(new Blob([svg], { type: 'image/svg+xml' }));
        try {
            const image = new Image();
            image.src = url;
            await image.decode();
            const canvas = document.createElement('canvas');
            canvas.width = width;
            canvas.height = height;
            const context = canvas.getContext('2d');
            if (!context) return null;
            context.drawImage(image, 0, 0, width, height);
            return await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, type));
        } catch {
            return null;
        } finally {
            URL.revokeObjectURL(url);
        }
    };
}
