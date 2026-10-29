
export const IMAGE_ACCEPT = 'image/png,image/jpeg,image/webp';

export function pickImageFile(): Promise<File | null> {
    return new Promise((resolve) => {
        const input = document.createElement('input');
        input.type = 'file';
        input.accept = IMAGE_ACCEPT;
        input.hidden = true;
        input.setAttribute('data-image-picker', '');
        const done = (file: File | null): void => {
            input.remove();
            resolve(file);
        };
        input.addEventListener('change', () => done(input.files?.[0] ?? null));
        input.addEventListener('cancel', () => done(null));
        document.body.appendChild(input);
        input.click();
    });
}
