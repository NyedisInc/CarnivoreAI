/** @vitest-environment jsdom */
import { describe, expect, it, vi } from 'vitest';
import { watchKeepAwakeRepaint } from './keep-awake-repaint';

describe('keep-awake repaint', () => {
    it('repaints on the change event and stops once removed', () => {
        const repaint = vi.fn();
        const stop = watchKeepAwakeRepaint(repaint);
        window.dispatchEvent(new CustomEvent('cloude:auto-sleep-changed'));
        expect(repaint).toHaveBeenCalledTimes(1);
        stop();
        window.dispatchEvent(new CustomEvent('cloude:auto-sleep-changed'));
        expect(repaint).toHaveBeenCalledTimes(1);
    });
});
