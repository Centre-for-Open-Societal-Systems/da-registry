'use client';

import { useCallback, useEffect, useId, useRef, useState, type DragEvent } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { documentUrl } from './files';
import {
    getValueByPath,
    setValueByPath,
    setValues,
    useWidgetContext,
    type WidgetRootState,
} from '@openg2p/registry-widgets';

export const PROFILE_PHOTO_VARIANT = 'oan-profile-photo';

// The shape the widget package's file collector recognises as a fresh upload.
type SerializedFile = {
    __type: 'File';
    name: string;
    type: string;
    size: number;
    lastModified: number;
    data: string;
};

type Config = Record<string, any>;

const ACCEPTED_TYPES = ['image/jpeg', 'image/png', 'image/webp'];
const DEFAULTS = { maxDimension: 1024, maxSizeKb: 2048, imageSize: 160, jpegQuality: 0.85 };

const LABELS: Record<string, string> = {
    profile_photo_upload: 'Upload photo',
    profile_photo_replace: 'Replace photo',
    profile_photo_remove: 'Remove',
    profile_photo_hint: 'JPEG, PNG or WebP. On a phone, take a photo or pick one from the gallery.',
    profile_photo_none: 'No photo',
    profile_photo_bad_type: 'Use a JPEG, PNG or WebP image.',
    profile_photo_too_large: 'The photo is larger than {size} KB after resizing. Choose a smaller image, or take the photo again.',
    profile_photo_unreadable: 'The image could not be read. Choose another photo, or take it again.',
};

const isSerializedFile = (value: unknown): value is SerializedFile =>
    !!value && typeof value === 'object' && (value as SerializedFile).__type === 'File';

const readAsBase64 = (blob: Blob): Promise<string> =>
    new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(String(reader.result).split(',')[1] ?? '');
        reader.onerror = () => reject(reader.error);
        reader.readAsDataURL(blob);
    });

// Scale the photo down so its longer side is at most maxDimension, as JPEG. A
// phone camera photo is several megabytes; the record needs a portrait.
async function shrink(file: File, maxDimension: number, quality: number): Promise<Blob> {
    const bitmap = await createImageBitmap(file);
    try {
        const scale = Math.min(1, maxDimension / Math.max(bitmap.width, bitmap.height));
        if (scale === 1 && file.type === 'image/jpeg') return file;
        const canvas = document.createElement('canvas');
        canvas.width = Math.round(bitmap.width * scale);
        canvas.height = Math.round(bitmap.height * scale);
        const context = canvas.getContext('2d');
        if (!context) return file;
        context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
        const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/jpeg', quality));
        return blob ?? file;
    } finally {
        bitmap.close();
    }
}

const jpegName = (name: string) => `${name.replace(/\.[^.]+$/, '') || 'photo'}.jpg`;

/**
 * Profile photo of a development agent on the form: one picker, see it straight away, replace
 * or remove it. A phone offers its camera or its gallery for an image input,
 * and a computer a file dialog, so one picker covers both.
 *
 * The picked photo is stored, as the widget package's serialized file, at the
 * widget's "imageUrl" path. On save the staff UI uploads it and sets the field
 * of the "image" path, record_image_document_id, which the record's header
 * shows as the development agent's picture. A stored photo arrives at "imageUrl" as a URL.
 *
 * Section metadata:
 *   widget: "header-section", widget-variant: "oan-profile-photo"
 *   widget-data-path: {image, imageUrl}
 *   widget-data-format: {imageSize, maxDimension, jpegQuality} (all optional)
 *   widget-data-validation: {maxSizeKb} (optional)
 */
export function ProfilePhotoWidget({ config }: { config: Config }) {
    const dispatch = useDispatch();
    const { t, schemaData } = useWidgetContext();
    const values = useSelector((state: WidgetRootState) => state.widget.values);
    const inputId = useId();
    const fileInput = useRef<HTMLInputElement>(null);
    const [error, setError] = useState<string | null>(null);
    const [busy, setBusy] = useState(false);
    const [dragging, setDragging] = useState(false);

    const paths = (config['widget-data-path'] ?? {}) as Record<string, string>;
    const format = { ...DEFAULTS, ...(config['widget-data-format'] ?? {}) };
    const maxSizeKb = Number(config['widget-data-validation']?.maxSizeKb ?? DEFAULTS.maxSizeKb);
    const readonly = config['widget-readonly'] !== false;

    const label = useCallback(
        (key: string, params?: Record<string, unknown>) => {
            const fallback = LABELS[key] ?? key;
            const text = t ? t(key, { defaultValue: fallback, ...params }) : fallback;
            const shown = !text || text === key ? fallback : text;
            return params ? shown.replace(/\{(\w+)\}/g, (_, name) => String(params[name] ?? '')) : shown;
        },
        [t],
    );
    const title = config['widget-label'] ? label(String(config['widget-label'])) : '';

    // The form's value when it has one, else the record's. A value the form set
    // to null (the photo was removed) must stay null: falling back to the
    // record there brought the removed photo back on screen.
    const read = (path: string | undefined) => {
        if (!path) return undefined;
        const inForm = getValueByPath(values, path);
        return inForm !== undefined ? inForm : getValueByPath(schemaData ?? {}, path);
    };
    const value = read(paths.imageUrl);

    // The photo's document id. An intake draft read back from the server has
    // the id but no link ("imageUrl" is only filled on the register), so the
    // link is fetched by id; without this a saved photo showed as "No photo".
    const storedId = read(paths.image);

    const [preview, setPreview] = useState<string | null>(null);
    useEffect(() => {
        let current = true;
        if (isSerializedFile(value) && value.data) setPreview(`data:${value.type};base64,${value.data}`);
        else if (typeof value === 'string' && value) setPreview(value);
        else if (value && typeof value === 'object' && typeof value.presigned_url === 'string') setPreview(value.presigned_url);
        else {
            setPreview(null);
            // value === null is a photo the user just removed: nothing to fetch.
            if (value !== null && typeof storedId === 'string' && storedId) {
                void documentUrl(storedId).then((url) => {
                    if (current && url) setPreview(url);
                });
            }
        }
        return () => {
            current = false;
        };
    }, [value, storedId]);

    const store = useCallback(
        (next: SerializedFile | null) => {
            if (!paths.imageUrl) return;
            let updated = setValueByPath({ ...values }, paths.imageUrl, next);
            // Removing the photo: the staff UI saves a section's files only when
            // one was added, so an emptied "imageUrl" alone is not a change.
            // Empty the field the record holds the photo in as well; it is saved
            // with the section and takes the photo off the record.
            if (next === null && paths.image) updated = setValueByPath(updated, paths.image, null);
            dispatch(setValues(updated));
        },
        [dispatch, paths.image, paths.imageUrl, values],
    );

    const accept = useCallback(
        async (file: File | undefined) => {
            if (!file) return;
            setError(null);
            if (!ACCEPTED_TYPES.includes(file.type)) {
                setError(label('profile_photo_bad_type'));
                return;
            }
            setBusy(true);
            try {
                const blob = await shrink(file, Number(format.maxDimension), Number(format.jpegQuality));
                if (blob.size > maxSizeKb * 1024) {
                    setError(label('profile_photo_too_large', { size: maxSizeKb }));
                    return;
                }
                const resized = blob !== file;
                store({
                    __type: 'File',
                    name: resized ? jpegName(file.name) : file.name,
                    type: resized ? 'image/jpeg' : file.type,
                    size: blob.size,
                    lastModified: file.lastModified || Date.now(),
                    data: await readAsBase64(blob),
                });
            } catch {
                setError(label('profile_photo_unreadable'));
            } finally {
                setBusy(false);
            }
        },
        [format.jpegQuality, format.maxDimension, label, maxSizeKb, store],
    );

    const onDrop = (event: DragEvent<HTMLDivElement>) => {
        event.preventDefault();
        setDragging(false);
        if (!readonly) void accept(event.dataTransfer.files?.[0]);
    };

    const size = Number(format.imageSize);
    const disabled = readonly || busy;

    return (
        <div className="oan-photo">
            <style>{`
                .oan-photo { display: flex; gap: 16px; align-items: center; flex-wrap: wrap; }
                .oan-photo-frame {
                    width: ${size}px; height: ${size}px; border-radius: 12px; overflow: hidden;
                    display: flex; align-items: center; justify-content: center; flex-shrink: 0;
                    background: var(--owt-color-bg-alt, #f5f5f5);
                    border: 2px dashed var(--owt-color-border, #d1d5db);
                    color: var(--owt-color-text-muted, #6b7280); font-size: 13px; text-align: center;
                }
                .oan-photo-frame.has-photo { border-style: solid; }
                .oan-photo-frame.dragging { border-color: var(--owt-color-primary, #ed7c22); }
                .oan-photo-frame img { width: 100%; height: 100%; object-fit: cover; }
                .oan-photo-side { display: flex; flex-direction: column; gap: 8px; min-width: 0; }
                .oan-photo-title { font-weight: 600; color: var(--owt-color-text, #111827); }
                .oan-photo-actions { display: flex; gap: 8px; flex-wrap: wrap; }
                .oan-photo-actions button {
                    height: 30px; padding: 0 12px; font-size: 14px; cursor: pointer;
                    border-radius: var(--owt-btn-border-radius, 6px);
                    background: var(--owt-btn-secondary-bg, #fff);
                    color: var(--owt-btn-secondary-color, #374151);
                    border: 1px solid var(--owt-btn-secondary-border, #d1d5db);
                }
                .oan-photo-actions button.primary {
                    background: var(--owt-btn-primary-bg, #ed7c22);
                    color: var(--owt-btn-primary-color, #fff);
                    border-color: var(--owt-btn-primary-border, #ed7c22);
                }
                .oan-photo-actions button:disabled { opacity: 0.5; cursor: default; }
                .oan-photo-hint { font-size: 12px; color: var(--owt-widget-helptext-color, #6b7280); }
                .oan-photo-error { font-size: 12px; color: var(--owt-widget-error-color, #dc2626); }
            `}</style>
            <div
                className={`oan-photo-frame${preview ? ' has-photo' : ''}${dragging ? ' dragging' : ''}`}
                onDragOver={(event) => {
                    if (readonly) return;
                    event.preventDefault();
                    setDragging(true);
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={onDrop}
            >
                {preview ? <img src={preview} alt={title || 'Profile photo'} /> : <span>{label('profile_photo_none')}</span>}
            </div>
            <div className="oan-photo-side">
                {title && <span className="oan-photo-title">{title}</span>}
                {!readonly && (
                    <>
                        <div className="oan-photo-actions">
                            <button type="button" className="primary" disabled={disabled} onClick={() => fileInput.current?.click()}>
                                {label(preview ? 'profile_photo_replace' : 'profile_photo_upload')}
                            </button>
                            {preview && (
                                <button
                                    type="button"
                                    disabled={disabled}
                                    onClick={() => {
                                        setError(null);
                                        store(null);
                                    }}
                                >
                                    {label('profile_photo_remove')}
                                </button>
                            )}
                        </div>
                        <span className="oan-photo-hint">{label('profile_photo_hint')}</span>
                        {error && (
                            <span className="oan-photo-error" role="alert">
                                {error}
                            </span>
                        )}
                        <input
                            ref={fileInput}
                            id={`${inputId}-file`}
                            type="file"
                            accept={ACCEPTED_TYPES.join(',')}
                            hidden
                            onChange={(event) => {
                                void accept(event.target.files?.[0]);
                                event.target.value = '';
                            }}
                        />
                    </>
                )}
            </div>
        </div>
    );
}
