/* <input class="oc-field hd-add-input" use:baseField={'sm'} /> */

export const BASE_FIELDS_HOST = 'data-base-fields';

const LEGACY_FIELD_CLASS = 'oc-field';

export function baseField(node: HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement, size?: 'sm'): { update: (next?: 'sm') => void; destroy: () => void } {
  const hosted = node.closest(`[${BASE_FIELDS_HOST}]`) !== null;
  const apply = (next?: 'sm'): void => {
    if (!hosted) return;
    node.classList.remove(LEGACY_FIELD_CLASS);
    node.setAttribute('data-field', '');
    if (next) node.setAttribute('data-size', next);
    else node.removeAttribute('data-size');
  };
  apply(size);
  return { update: apply, destroy: () => {} };
}
