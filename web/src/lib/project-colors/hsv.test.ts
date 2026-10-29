import { describe, expect, it } from 'vitest';
import { hsvToRgb, rgbToHsv } from './hsv';

describe('hsv helpers', () => {
    it('maps the primaries', () => {
        expect(hsvToRgb(0, 1, 1)).toEqual([255, 0, 0]);
        expect(hsvToRgb(120, 1, 1)).toEqual([0, 255, 0]);
        expect(hsvToRgb(240, 1, 1)).toEqual([0, 0, 255]);
        expect(hsvToRgb(360, 1, 1)).toEqual([255, 0, 0]);
    });
    it('maps white, black and gray', () => {
        expect(hsvToRgb(200, 0, 1)).toEqual([255, 255, 255]);
        expect(hsvToRgb(200, 1, 0)).toEqual([0, 0, 0]);
        expect(rgbToHsv(56, 56, 56, 90)[0]).toBe(90);
        expect(rgbToHsv(0, 0, 0, 90)).toEqual([90, 0, 0]);
    });
    it('clamps garbage', () => {
        expect(hsvToRgb(NaN, 2, -1)).toEqual([0, 0, 0]);
        expect(rgbToHsv(300, -5, NaN)).toEqual([0, 1, 1]);
    });
    it('round trips every channel combination on a coarse grid', () => {
        for (let r = 0; r < 256; r += 17) for (let g = 0; g < 256; g += 17) for (let b = 0; b < 256; b += 17) {
            const [h, s, v] = rgbToHsv(r, g, b);
            expect(hsvToRgb(h, s, v)).toEqual([r, g, b]);
        }
    });
});
