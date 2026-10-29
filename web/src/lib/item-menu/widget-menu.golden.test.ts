import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, test } from 'vitest';
import type { MenuNode } from '../drawer-tabs/add-component-menu';
import type { WidgetMenuCtx } from '../widget-menu/model';
import { widgetMenuNodes } from './widget-nodes';
import { goldenOfNodes, type GoldenEntry } from './golden-normalize';

const GOLDEN = path.join(__dirname, '__goldens__', 'widget-menus.json');

const leaf = (id: string, extra: Partial<MenuNode> = {}): MenuNode => ({ id, label: id, run: () => {}, ...extra });
const noop = (): void => {};

const CASES: Record<string, WidgetMenuCtx> = {
    'normal bare': { editing: false, onClose: noop, close: { run: noop } },
    'normal full': {
        editing: false, onClose: noop,
        content: [[leaf('sort:name', { checked: true }), leaf('sort:recent', { checked: false })], [leaf('view-all')]],
        popOut: noop, header: { shown: true, toggle: noop }, editLayout: noop, close: { run: noop },
    },
    'normal scope switch': {
        editing: false, onClose: noop,
        scopeViews: [leaf('session', { checked: true }), leaf('all', { checked: false })],
        popOut: noop, header: { shown: false, toggle: noop }, editLayout: noop, close: { run: noop, instance: true },
    },
    'normal on a bar': { editing: false, onClose: noop, editLayout: noop, close: { run: noop } },
    'normal pop-out window': { editing: false, onClose: noop, focusMain: noop, header: { shown: true, toggle: noop } },
    'normal tab': { editing: false, onClose: noop, popOut: noop, editLayout: noop, tab: { moveTo: noop, splitRight: noop, splitDown: noop, close: noop } },
    'edit full': {
        editing: true, onClose: noop,
        content: [[leaf('view-all')]],
        views: [leaf('compact', { checked: true }), leaf('detailed', { checked: false })],
        settings: [[leaf('settings')]],
        popOut: noop, header: { shown: true, toggle: noop },
        arrange: [{ item: 'extendRow', run: noop }, { item: 'pullBackRow', blocked: 'one row now', run: noop }, { item: 'moveUp', run: noop }, { item: 'moveDown', blocked: 'already last', run: noop }, { item: 'moveToDrawer', run: noop }, { item: 'moveToBar', label: 'move to the right bar', run: noop }],
        editLayout: noop, close: { run: noop },
    },
    'edit with branch content': {
        editing: true, onClose: noop,
        content: [[{ id: 'filter', label: 'filter', children: [leaf('all', { checked: true }), leaf('mine', { checked: false })] }]],
        editLayout: noop, close: { run: noop, instance: true },
    },
};

describe('the widget menu golden', () => {
    test('every representative widget state offers exactly the recorded menu', () => {
        const now: Record<string, GoldenEntry[]> = {};
        for (const [name, ctx] of Object.entries(CASES)) now[name] = goldenOfNodes(widgetMenuNodes(ctx));
        if (process.env.RECORD_GOLDENS === '1') fs.writeFileSync(GOLDEN, `${JSON.stringify(now, null, 2)}\n`);
        const golden = JSON.parse(fs.readFileSync(GOLDEN, 'utf8')) as Record<string, GoldenEntry[]>;
        expect(Object.keys(now)).toEqual(Object.keys(golden));
        for (const name of Object.keys(golden)) expect(now[name], name).toEqual(golden[name]);
    });
});
