// A file not yet uploaded, as the widget package's file widget saves it in the
// form's values: the section save uploads it and stores it as a document.
export type SerializedFile = {
    __type: 'File';
    name: string;
    type: string;
    size: number;
    lastModified: number;
    data: string;
};

export const isSerializedFile = (value: unknown): value is SerializedFile =>
    !!value && typeof value === 'object' && (value as SerializedFile).__type === 'File';

const readAsBase64 = (file: File): Promise<string> =>
    new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result).split(',')[1] ?? '');
        reader.onerror = () => reject(reader.error);
        reader.readAsDataURL(file);
    });

export async function serializeFile(file: File): Promise<SerializedFile> {
    return {
        __type: 'File',
        name: file.name,
        type: file.type,
        size: file.size,
        lastModified: file.lastModified || Date.now(),
        data: await readAsBase64(file),
    };
}

/**
 * Whether a file is one an `accept` list (".pdf,.jpg,image/png", as on a file
 * input) allows. The input's own filter can be switched to "All files", so a
 * widget checks again before taking the file. No list accepts any file.
 */
export function accepts(file: File, accept: string | undefined): boolean {
    const allowed = (accept ?? '').split(',').map((a) => a.trim().toLowerCase()).filter(Boolean);
    if (!allowed.length) return true;
    const name = file.name.toLowerCase();
    const type = (file.type || '').toLowerCase();
    return allowed.some((a) =>
        a.startsWith('.') ? name.endsWith(a) : a.endsWith('/*') ? type.startsWith(a.slice(0, -1)) : type === a,
    );
}

/** An `accept` list as a reader says it: ".pdf,.jpg,.jpeg" -> "PDF, JPG or JPEG". */
export function acceptedTypes(accept: string | undefined): string {
    const names = (accept ?? '')
        .split(',')
        .map((a) => a.trim().replace(/^\./, '').replace(/\/\*$/, '').toUpperCase())
        .filter(Boolean);
    return names.length > 1 ? `${names.slice(0, -1).join(', ')} or ${names[names.length - 1]}` : (names[0] ?? '');
}

/** Open a file not yet uploaded in a new tab. */
export function openSerializedFile(file: SerializedFile) {
    const bytes = Uint8Array.from(atob(file.data), (c) => c.charCodeAt(0));
    const url = URL.createObjectURL(new Blob([bytes], { type: file.type || 'application/octet-stream' }));
    window.open(url, '_blank', 'noopener');
    setTimeout(() => URL.revokeObjectURL(url), 60000);
}
