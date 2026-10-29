import { expect, test } from 'vitest';
import { isPageSlot, isPageTab, pageIdOfTab, pageSlotFor, pageTabId, pageTabOfRowName } from './page-tabs';
import { isTabSlot } from './tabs';

const ID = '0123456789abcdef';

test('a page tab round-trips its id and nothing else is a page tab', () => {
  expect(pageTabId(ID)).toBe(`page:${ID}`);
  expect(pageIdOfTab(pageTabId(ID))).toBe(ID);
  for (const bad of ['terminal:row:7', 'terminal:@primary', 'page:', 'page:0123', `page:${ID.toUpperCase()}`, `page:${ID}0`, 'cloude_api', '']) {
    expect(isPageTab(bad), bad).toBe(false);
  }
});

test('a sidebar row name is a page tab only for a browser-kind row', () => {
  expect(pageTabOfRowName(`browser:${ID}`)).toBe(`page:${ID}`);
  for (const name of ['cloude_api', 'carnivore_x', 'browser:zz', `browser:${ID}0`, `layout:${ID}`, '']) {
    expect(pageTabOfRowName(name), name).toBeNull();
  }
});

test('the slot for a split-out page is a free terminal slot, numbered when taken', () => {
  const slot = pageSlotFor(pageTabId(ID), ['terminal:@primary']);
  expect(slot).toBe(`terminal:pg-${ID}`);
  expect(isTabSlot(slot!)).toBe(true);
  expect(isPageSlot(slot!)).toBe(true);
  expect(pageSlotFor(pageTabId(ID), [slot!])).toBe(`terminal:pg-${ID}-2`);
  expect(pageSlotFor('terminal:row:7', [])).toBeNull();
  expect(isPageSlot('terminal:row:7')).toBe(false);
});
