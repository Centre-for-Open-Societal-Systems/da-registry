'use client';

import { useCallback, useRef, useState } from 'react';
import { useWidgetContext } from '@openg2p/registry-widgets';
import { accepts, acceptedTypes, documentUrl, isSerializedFile, openSerializedFile, serializeFile } from './files';

type Config = Record<string, any>;

type Props = {
    config: Config;
    value?: unknown;
    onChange?: (value: unknown) => void;
    onBlur?: () => void;
    isEnabled?: boolean;
};

type StoredFile = { document_id: string; name?: string };

const LABELS: Record<string, string> = {
    documents_add: 'Add file',
    documents_full: 'Up to {count} files can be attached here. Remove one to add another.',
    documents_view: 'View',
    documents_remove: 'Remove',
    documents_too_large: 'The file is larger than {size} MB. Choose a smaller file, or scan it again at a lower resolution.',
    documents_bad_type: '{name} cannot be attached here. Choose a {types} file.',
    documents_duplicate: '{name} is already attached to this record.',
    documents_not_available: 'The file could not be opened. Try again.',
};

const isStored = (value: unknown): value is StoredFile =>
    !!value && typeof value === 'object' && typeof (value as StoredFile).document_id === 'string';

const asList = (value: unknown): unknown[] => {
    let list = value;
    if (typeof list === 'string') {
        try {
            list = JSON.parse(list);
        } catch {
            return [];
        }
    }
    return Array.isArray(list) ? list.filter((item) => isSerializedFile(item) || isStored(item)) : [];
};

/**
 * Several files in one table cell: the certificates of one education &
 * professional record. The widget package's file widget cannot be used in a
 * table, and its section uploader does not cover files in table rows, so the
 * cell holds a list: a new file as the package serializes it (base64), a saved
 * one as {document_id, name}. The register's domain service stores each new
 * file as a document when the row is saved.
 *
 * Section metadata (a table column):
 *   widget: "oan-file-list-cell"
 *   widget-data-options: {accept, maxSize (bytes), maxFiles}
 */
export function FileListCellWidget({ config, value, onChange, onBlur, isEnabled = true }: Props) {
    const { t } = useWidgetContext();
    const input = useRef<HTMLInputElement>(null);
    const [message, setMessage] = useState<string | null>(null);
    const options = (config['widget-data-options'] ?? {}) as { accept?: string; maxSize?: number; maxFiles?: number };
    const maxSize = Number(options.maxSize ?? 0);
    const maxFiles = Number(options.maxFiles ?? 3);
    const enabled = isEnabled && config['widget-readonly'] !== true;
    const files = asList(value);
    const title = String(config['widget-label'] ?? '');

    const label = useCallback(
        (key: string, params?: Record<string, unknown>) => {
            const fallback = LABELS[key] ?? key;
            const text = t ? t(key, { defaultValue: fallback }) : fallback;
            const shown = !text || text === key ? fallback : text;
            return params ? shown.replace(/\{(\w+)\}/g, (_, name) => String(params[name] ?? '')) : shown;
        },
        [t],
    );

    const nameOf = (file: unknown) =>
        isSerializedFile(file) ? file.name : isStored(file) ? file.name || 'certificate' : '';

    const set = (next: unknown[]) => {
        onChange?.(next.length ? next : null);
        onBlur?.();
    };

    const add = async (picked: File[]) => {
        setMessage(null);
        const names = new Set(files.map((file) => nameOf(file).toLowerCase()));
        const taken: File[] = [];
        for (const file of picked) {
            if (!accepts(file, options.accept)) {
                setMessage(label('documents_bad_type', { name: file.name, types: acceptedTypes(options.accept) }));
            } else if (maxSize && file.size > maxSize) {
                setMessage(label('documents_too_large', { size: Math.round(maxSize / 1048576) }));
            } else if (names.has(file.name.toLowerCase())) {
                setMessage(label('documents_duplicate', { name: file.name }));
            } else {
                names.add(file.name.toLowerCase());
                taken.push(file);
            }
        }
        const room = maxFiles - files.length;
        if (taken.length > room) setMessage(label('documents_full', { count: maxFiles }));
        const added = await Promise.all(taken.slice(0, Math.max(room, 0)).map(serializeFile));
        if (added.length) set([...files, ...added]);
    };

    const view = async (file: unknown) => {
        setMessage(null);
        if (isSerializedFile(file)) {
            openSerializedFile(file);
            return;
        }
        if (!isStored(file)) return;
        const url = await documentUrl(file.document_id);
        if (url) window.open(url, '_blank', 'noopener');
        else setMessage(label('documents_not_available'));
    };

    return (
        <div className="oan-file-list">
            <style>{`
                .oan-file-list { min-width: 240px; }
                .oan-file-list-title { font-weight: 500; margin-bottom: 8px; color: var(--owt-color-text, #111827); }
                .oan-file-list-items { display: flex; flex-direction: column; gap: 8px; margin-bottom: 8px; }
                .oan-file-list-item {
                    display: flex; align-items: center; gap: 8px; padding: 4px 8px; font-size: 13px;
                    border: 1px solid var(--owt-color-border, #d1d5db); border-radius: 8px;
                }
                .oan-file-list-item span { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
                .oan-file-list button {
                    height: 30px; padding: 0 12px; font-size: 14px; cursor: pointer; white-space: nowrap;
                    background: var(--owt-btn-secondary-bg, #fff); color: var(--owt-btn-secondary-color, #374151);
                    border: 1px solid var(--owt-color-primary-dark, #d1d5db); border-radius: 6px;
                }
                .oan-file-list button:disabled { opacity: 0.5; cursor: default; }
                .oan-file-list-add { border-style: dashed !important; }
                .oan-file-list-note { font-size: 12px; color: var(--owt-widget-helptext-color, #6b7280); margin-top: 8px; }
                .oan-file-list-error { font-size: 12px; color: var(--owt-widget-error-color, #dc2626); margin-top: 8px; }
            `}</style>
            {title && <div className="oan-file-list-title">{title}</div>}
            {files.length > 0 && (
                <div className="oan-file-list-items">
                    {files.map((file, index) => (
                        <div key={`${nameOf(file)}-${index}`} className="oan-file-list-item" title={nameOf(file)}>
                            <span>{nameOf(file)}</span>
                            <button type="button" onClick={() => void view(file)}>{label('documents_view')}</button>
                            {enabled && (
                                <button type="button" onClick={() => { setMessage(null); set(files.filter((_, i) => i !== index)); }}>
                                    {label('documents_remove')}
                                </button>
                            )}
                        </div>
                    ))}
                </div>
            )}
            {enabled && (
                <>
                    <button type="button" className="oan-file-list-add" disabled={files.length >= maxFiles}
                            onClick={() => input.current?.click()}>
                        + {label('documents_add')}
                    </button>
                    <div className="oan-file-list-note">{label('documents_full', { count: maxFiles })}</div>
                    <input
                        ref={input}
                        type="file"
                        multiple
                        accept={options.accept}
                        hidden
                        onChange={(event) => {
                            void add(Array.from(event.target.files ?? []));
                            event.target.value = '';
                        }}
                    />
                </>
            )}
            {message && <div className="oan-file-list-error" role="alert">{message}</div>}
        </div>
    );
}
