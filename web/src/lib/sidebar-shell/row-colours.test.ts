/** @vitest-environment jsdom */
import { describe, expect, it } from 'vitest';
import { loadLegacyDrawer } from './legacy-fixture';

const colour = () => loadLegacyDrawer().SessionSidebarGroupColour as {
    layoutRowAttrs(layout: unknown): string;
};

describe('layout row colour attributes', () => {
    it('a palette key is stamped as it always was', () => {
        expect(colour().layoutRowAttrs({ colour: 'teal', gradient: null, animation: 'none' })).toBe(' data-layout-colour="teal"');
    });

    it('a custom hex is stamped as custom with its lowercase inline hue', () => {
        expect(colour().layoutRowAttrs({ colour: '#6C799F', gradient: null, animation: 'pulse' }))
            .toBe(' data-layout-colour="custom" style="--row-hue: #6c799f" data-layout-anim="pulse"');
    });

    it('a gradient keeps its own stops, so no inline hue overrides the first one', () => {
        expect(colour().layoutRowAttrs({ colour: '#6c799f', gradient: 'tide', animation: 'none' }))
            .toBe(' data-layout-colour="custom" data-layout-gradient="tide"');
    });

    it('a value that is neither a key nor a hex is dropped', () => {
        expect(colour().layoutRowAttrs({ colour: 'indigo', gradient: null, animation: 'none' })).toBe('');
        expect(colour().layoutRowAttrs({ colour: '#12345', gradient: null, animation: 'none' })).toBe('');
    });
});
