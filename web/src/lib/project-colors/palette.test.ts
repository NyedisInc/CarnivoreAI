import { expect, test } from 'vitest';
import { SOFT_PROJECT_COLORS, isHexColor, isProjectColor, projectColorName, projectColorVar } from './palette';

test('a hex paints as itself, anything else (a legacy color name included) as the quiet text token', () => {
  expect(projectColorVar('#FF0000')).toBe('#ff0000');
  for (const name of ['cyan', 'orange', 'green-bright', 'pink']) {
    expect(projectColorVar(name)).toBe('var(--oc-text-secondary)');
    expect(isProjectColor(name)).toBe(false);
  }
  expect(projectColorVar(null)).toBe('var(--oc-text-secondary)');
  expect(isProjectColor('#c17b87')).toBe(true);
  expect(isHexColor('#abc')).toBe(false);
});

test('every soft swatch is a distinct soft hex with a name, and names resolve both ways', () => {
  expect(new Set(SOFT_PROJECT_COLORS.map((s) => s.hex)).size).toBe(SOFT_PROJECT_COLORS.length);
  for (const swatch of SOFT_PROJECT_COLORS) {
    expect(isHexColor(swatch.hex)).toBe(true);
    expect(projectColorName(swatch.hex.toUpperCase())).toBe(swatch.name);
  }
  expect(projectColorName('#010203')).toBeNull();
  expect(projectColorName('cyan')).toBeNull();
});
