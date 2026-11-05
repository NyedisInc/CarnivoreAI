/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';

import { settingsFragment } from '../../lib/settings-page/settings-hash';
import { FEATURES_HASH, openFeaturesPage } from './features-page';

afterEach(() => {
    window.location.hash = '';
});

describe('openFeaturesPage', () => {
    test('the literal fragment is the settings module\'s own for the features section', () => {
        expect(FEATURES_HASH).toBe(settingsFragment('features'));
    });

    test('writes the fragment and reports that it opened', () => {
        expect(openFeaturesPage()).toBe(true);
        expect(window.location.hash).toBe(FEATURES_HASH);
    });
});
