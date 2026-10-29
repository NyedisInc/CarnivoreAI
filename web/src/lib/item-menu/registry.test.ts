import { describe, expect, test } from 'vitest';
import type { MenuNode } from '../drawer-tabs/add-component-menu';
import './menus/all';
import { contributeItemMenu, defineItemMenu, definedItemMenuTypes, itemMenu, ItemMenuError } from './registry';
import { widgetMenuNodes } from './widget-nodes';

const env = { close: () => {}, glyph: () => '' };
const leaf = (id: string, extra: Partial<MenuNode> = {}): MenuNode => ({ id, label: id, run: () => {}, ...extra });

describe('the item menu registry', () => {
    test('every item type the drawer and the widgets carry is defined', () => {
        expect(definedItemMenuTypes().sort()).toEqual(['browser', 'color', 'company', 'file', 'group', 'layout', 'leader', 'page', 'pagerow', 'project', 'session', 'widget']);
    });

    test('a type cannot be defined twice', () => {
        expect(() => defineItemMenu('widget', { build: () => null })).toThrow(ItemMenuError);
    });

    test('an unknown type is refused, never answered with an empty menu', () => {
        expect(() => itemMenu('nope' as never, {} as never, env)).toThrow(ItemMenuError);
    });

    test('a contribution joins as its own group above the destructive group, and leaves when removed', () => {
        const ctx = { editing: false, onClose: () => {}, popOut: () => {}, close: { run: () => {} } };
        expect(widgetMenuNodes(ctx).map((n) => n.id)).toEqual(['pop-out', 'close-widget']);
        const remove = contributeItemMenu('widget', { id: 'test', nodes: () => [leaf('plug-a'), leaf('plug-b')] });
        const nodes = widgetMenuNodes(ctx);
        expect(nodes.map((n) => n.id)).toEqual(['pop-out', 'plug-a', 'plug-b', 'close-widget']);
        expect(nodes.map((n) => !!n.sep)).toEqual([false, true, false, true]);
        expect(() => contributeItemMenu('widget', { id: 'test', nodes: () => [] })).toThrow(ItemMenuError);
        remove();
        expect(widgetMenuNodes(ctx).map((n) => n.id)).toEqual(['pop-out', 'close-widget']);
    });

    test('a contributed leaf acts, then closes the menu like every other leaf', () => {
        const log: string[] = [];
        const remove = contributeItemMenu('widget', { id: 'acts', nodes: () => [leaf('plug', { run: () => log.push('act') })] });
        widgetMenuNodes({ editing: false, onClose: () => log.push('close') }).find((n) => n.id === 'plug')!.run!();
        remove();
        expect(log).toEqual(['act', 'close']);
    });

    test('a contribution that offers nothing adds no hairline, and one on a menu with no destructive entry goes last', () => {
        const remove = contributeItemMenu('widget', { id: 'empty', nodes: () => [] });
        const ctx = { editing: false, onClose: () => {}, popOut: () => {} };
        expect(widgetMenuNodes(ctx).map((n) => n.id)).toEqual(['pop-out']);
        remove();
        const removeLast = contributeItemMenu('widget', { id: 'last', nodes: () => [leaf('plug')] });
        expect(widgetMenuNodes(ctx).map((n) => [n.id, !!n.sep])).toEqual([['pop-out', false], ['plug', true]]);
        removeLast();
    });
});
