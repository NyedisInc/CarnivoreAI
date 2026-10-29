/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { beforeAll, describe, expect, it } from 'vitest';

const read = (p: string): string => fs.readFileSync(path.join(process.cwd(), '..', p), 'utf8');

describe('row cursor', () => {
    beforeAll(() => {
        const style = document.createElement('style');
        style.textContent = [
            'client/css/session-sidebar-rows.css', 'client/css/session-sidebar-row-controls.css', 'client/css/session-sidebar-row-bodies.css',
        ].map(read).join('\n') + '\n' + fs.readFileSync(path.join(__dirname, 'row-polish.css'), 'utf8');
        document.head.appendChild(style);
        document.body.innerHTML = `<div class="session-sidebar-list"><div class="session-sidebar-row" role="option">
            <div class="session-sidebar-row-main"><span class="status-dot"></span><span class="session-sidebar-row-name">n</span>
            <span class="session-row-live__part">x</span><button class="pin">p</button><input class="rename"></div></div></div>`;
    });

    const cursor = (sel: string): string => getComputedStyle(document.querySelector(sel)!).cursor;

    it('shows the pointer on the row, its main box, its name, its status light and its live parts', () => {
        for (const sel of ['.session-sidebar-row', '.session-sidebar-row-main', '.session-sidebar-row-name', '.status-dot', '.session-row-live__part', '.pin']) {
            expect(cursor(sel), sel).toBe('pointer');
        }
    });

    it('a text field keeps its own cursor', () => {
        expect(cursor('.rename')).not.toBe('pointer');
    });

    it('a drag in flight still shows grabbing', () => {
        document.querySelector('.session-sidebar-list')!.classList.add('session-sidebar-list--dragging');
        expect(cursor('.session-sidebar-row-main')).toBe('grabbing');
        expect(cursor('.session-sidebar-row-name')).toBe('grabbing');
        document.querySelector('.session-sidebar-list')!.classList.remove('session-sidebar-list--dragging');
    });
});
