'use client';

import { createElement, useCallback, useState } from 'react';
import { useSelector } from 'react-redux';
import {
    DialogTableWidget,
    getValueByPath,
    useWidgetContext,
    type WidgetRootState,
} from '@openg2p/registry-widgets';
import { documentUrl, isSerializedFile, openSerializedFile } from './files';

type Config = Record<string, any>;
type StoredFile = { document_id: string; name?: string };

export const FILE_LIST_CELL = 'oan-file-list-cell';

const LABELS: Record<string, string> = {
    documents_view: 'View',
    documents_not_available: 'The file could not be opened. Try again.',
};

const isStored = (value: unknown): value is StoredFile =>
    !!value && typeof value === 'object' && typeof (value as StoredFile).document_id === 'string';

const filesOf = (value: unknown): unknown[] => {
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

// "SENIOR_DA" -> "Senior da": a code is all the table's row has for a dropdown.
const readable = (value: unknown): string => {
    const text = String(value ?? '').trim();
    if (!/^[A-Z0-9_]+$/.test(text) || /^\d+$/.test(text)) return text;
    const words = text.replace(/_/g, ' ').toLowerCase();
    return words.charAt(0).toUpperCase() + words.slice(1);
};

/**
 * The platform's table with "Add record", plus the files of its rows.
 *
 * The table shows a cell as text, so a row's files (a column of type
 * "oan-file-list-cell") read "Attached" and could only be opened through Edit
 * details. Under the table this lists each row's files with a View button, on
 * the register page and on the form alike. A table without such a column, or
 * with no file, is the platform's table unchanged.
 *
 * Section metadata, on the file column (optional):
 *   widget-data-options: {rowLabelColumns: ["education_level", "passout_year"]}
 * names the columns that tell the rows apart; the first column is the default.
 */
export function RecordFilesTableWidget(props: { config: Config }) {
    const { config } = props;
    const { t, schemaData } = useWidgetContext();
    const values = useSelector((state: WidgetRootState) => state.widget.values);
    const [message, setMessage] = useState<string | null>(null);

    const label = useCallback(
        (key: string) => {
            const fallback = LABELS[key] ?? key;
            const text = t ? t(key, { defaultValue: fallback }) : fallback;
            return !text || text === key ? fallback : text;
        },
        [t],
    );

    const table = createElement(DialogTableWidget, props as never);
    const columns: Config[] = Array.isArray(config['widget-data-columns']) ? config['widget-data-columns'] : [];
    const fileColumn = columns.find((column) => column.widget === FILE_LIST_CELL);
    if (!fileColumn) return table;

    const path = String(config['widget-data-path'] ?? '');
    const stored = getValueByPath(values, path);
    const rows = (stored !== undefined ? stored : getValueByPath(schemaData ?? {}, path)) as unknown;
    const labelColumns: string[] = Array.isArray(fileColumn['widget-data-options']?.rowLabelColumns)
        ? fileColumn['widget-data-options'].rowLabelColumns
        : columns.slice(0, 1).map((column) => String(column['column-key']));

    const entries = (Array.isArray(rows) ? rows : [])
        .filter((row) => row && typeof row === 'object' && (row as Config).edit_action !== 'DELETE')
        .flatMap((row, rowIndex) => {
            const [first, ...rest] = labelColumns.map((key) => readable((row as Config)[key])).filter(Boolean);
            const rowLabel = first ? first + (rest.length ? ` (${rest.join(', ')})` : '') : `#${rowIndex + 1}`;
            return filesOf((row as Config)[String(fileColumn['column-key'])]).map((file, fileIndex) => ({
                key: `${rowIndex}-${fileIndex}`,
                rowLabel,
                file,
                name: isSerializedFile(file) ? file.name : (file as StoredFile).name || 'file',
            }));
        });
    if (!entries.length) return table;

    const view = async (file: unknown) => {
        setMessage(null);
        if (isSerializedFile(file)) {
            openSerializedFile(file);
            return;
        }
        const url = await documentUrl((file as StoredFile).document_id);
        if (url) window.open(url, '_blank', 'noopener');
        else setMessage(label('documents_not_available'));
    };

    const title = String(fileColumn['widget-label'] ?? '');
    return (
        <div className="oan-record-files">
            <style>{`
                .oan-record-files-list { margin-top: 12px; }
                .oan-record-files-title { font-weight: 500; margin-bottom: 8px; color: var(--owt-color-text, #111827); }
                .oan-record-files-row {
                    display: flex; align-items: center; gap: 12px; padding: 6px 0; font-size: 14px;
                    border-top: 1px solid var(--owt-widget-table-row-divider, #e5e7eb);
                }
                .oan-record-files-row:first-of-type { border-top: 0; }
                .oan-record-files-of { flex: 0 0 220px; color: var(--owt-widget-helptext-color, #6b7280); }
                .oan-record-files-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
                .oan-record-files-row button {
                    height: 30px; padding: 0 12px; font-size: 14px; cursor: pointer; white-space: nowrap;
                    background: var(--owt-btn-secondary-bg, #fff); color: var(--owt-btn-secondary-color, #374151);
                    border: 1px solid var(--owt-color-primary-dark, #d1d5db); border-radius: 6px;
                }
                .oan-record-files-error { font-size: 12px; color: var(--owt-widget-error-color, #dc2626); margin-top: 8px; }
                @media (max-width: 640px) { .oan-record-files-of { flex-basis: 110px; } }
            `}</style>
            {table}
            <div className="oan-record-files-list">
                {title && <div className="oan-record-files-title">{title}</div>}
                {entries.map((entry) => (
                    <div key={entry.key} className="oan-record-files-row" title={entry.name}>
                        <span className="oan-record-files-of">{entry.rowLabel}</span>
                        <span className="oan-record-files-name">{entry.name}</span>
                        <button type="button" onClick={() => void view(entry.file)}>{label('documents_view')}</button>
                    </div>
                ))}
                {message && <div className="oan-record-files-error" role="alert">{message}</div>}
            </div>
        </div>
    );
}
