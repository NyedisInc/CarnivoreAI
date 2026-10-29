import { describe, expect, test } from 'vitest';
import { splitSentText } from './chat-upload';

describe('splitSentText upload folders', () => {
  test.each(['.carnivore_uploads', '.cloude_uploads'])('a picture under %s is pulled out of the text', (folder) => {
    const path = `/proj/${folder}/ab12cd34-a.png`;
    expect(splitSentText(`look\n${path}`)).toEqual({ text: 'look', images: [path] });
  });
  test.each(['.cloude_uploads_x', '.carnivore_uploadsX', '.uploads'])('a picture under %s stays in the text', (folder) => {
    const text = `look\n/proj/${folder}/ab12cd34-a.png`;
    expect(splitSentText(text)).toEqual({ text, images: [] });
  });
});
