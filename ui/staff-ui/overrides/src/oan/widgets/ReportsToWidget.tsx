'use client';

import { useCallback, useEffect, useRef, useState, type UIEvent } from 'react';
import { useBaseWidget, useWidgetContext } from '@openg2p/registry-widgets';

type Config = Record<string, any>;
type Person = { id: string; name: string; position: string };

const LABELS: Record<string, string> = {
    reports_to_choose: 'Choose a person',
    reports_to_change: 'Change',
    reports_to_clear: 'Clear',
    reports_to_title: 'Choose the person this one reports to',
    reports_to_search: 'ID or name',
    reports_to_all_positions: 'All positions',
    reports_to_id: 'ID',
    reports_to_name: 'Name',
    reports_to_position: 'Position',
    reports_to_their_name: 'Reports to (name)',
    reports_to_their_position: 'Reports to (position)',
    reports_to_not_found: 'Not found',
    reports_to_loading: 'Loading…',
    reports_to_failed: 'The list could not be loaded. Close this window and try again.',
    reports_to_unknown: 'No one in the register has the ID {id}. Choose the person again.',
    reports_to_cancel: 'Cancel',
};

const field = (row: Record<string, any>, name: string): string => {
    const found = Array.isArray(row.display_fields)
        ? row.display_fields.find((f: Record<string, any>) => f?.field_name === name)
        : null;
    return found?.value == null ? '' : String(found.value);
};

const person = (row: Record<string, any>): Person => ({
    id: String(row.functional_record_id ?? ''),
    name: String(row.record_name ?? ''),
    position: field(row, 'position'),
});

async function post(url: string, body: Record<string, unknown>): Promise<any> {
    const { withCsrfHeaders } = await import('@/shared/utils/csrf');
    const response = await fetch(url, {
        method: 'POST',
        headers: withCsrfHeaders('POST', { 'Content-Type': 'application/json' }),
        credentials: 'include',
        body: JSON.stringify(body),
    });
    if (!response.ok) throw new Error(String(response.status));
    return response.json();
}

/**
 * "Reports to": the DA-ID of the person this one reports to, chosen from the
 * register. The box opens a list of the people in the register, ten at a time
 * (scroll for more), narrowed by an ID or a name and by position. Choosing
 * one stores their DA-ID and shows their name and position under the box, as
 * "Reports to (name)" and "Reports to (position)" so they are not read as the
 * record's own; they are read from the register each time, not stored, so
 * they follow that person's record.
 *
 * Metadata:
 *   widget: "oan-reports-to"
 *   widget-data-path: "<register_id>.reports_to"
 *   oan-lookup: {register_id, page_size (default 10), position_attribute}
 * The list is the register's own search (the staff UI's /api/register/records),
 * so a user sees the people their role lets them see.
 */
export function ReportsToWidget({ config }: { config: Config }) {
    const { value, onChange, error, touched, isVisible, isEnabled, isRequired } = useBaseWidget({ config: config as never });
    const { t, schemaData } = useWidgetContext();
    const lookup = (config['oan-lookup'] ?? {}) as { register_id?: string; page_size?: number; position_attribute?: string };
    const registerId = lookup.register_id ?? '';
    const pageSize = Number(lookup.page_size ?? 10);
    const readonly = !!config['widget-readonly'];
    const chosenId = value == null ? '' : String(value).trim();
    // The record's own DA-ID: a person does not report to themselves.
    const ownId = String((schemaData as Record<string, any> | undefined)?.[registerId]?.functional_record_id ?? '');

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

    // Position codes as the list shows them ("SENIOR_DA" -> "Senior DA").
    const [positions, setPositions] = useState<{ code: string; name: string }[]>([]);
    useEffect(() => {
        if (!lookup.position_attribute) return;
        let current = true;
        post('/api/attributes/values', { attribute_id: lookup.position_attribute, page_size: 500 })
            .then((rows) => {
                if (!current || !Array.isArray(rows)) return;
                setPositions(rows.map((r: Record<string, any>) => ({ code: String(r.value_id ?? ''), name: String(r.value_display ?? r.value_id ?? '') })));
            })
            .catch(() => undefined);
        return () => {
            current = false;
        };
    }, [lookup.position_attribute]);
    const positionName = (code: string) => positions.find((p) => p.code === code)?.name ?? code;

    // The chosen person, read from the register by the stored DA-ID.
    const [chosen, setChosen] = useState<Person | null>(null);
    const [unknown, setUnknown] = useState(false);
    useEffect(() => {
        if (!chosenId) {
            setChosen(null);
            setUnknown(false);
            return;
        }
        if (chosen?.id === chosenId) return;
        let current = true;
        post('/api/register/records', { register_id: registerId, current_page: 1, page_size: 5, search_text: chosenId })
            .then((body) => {
                if (!current) return;
                const row = (body?.records ?? []).find((r: Record<string, any>) => String(r.functional_record_id) === chosenId);
                setChosen(row ? person(row) : null);
                setUnknown(!row);
            })
            .catch(() => undefined);
        return () => {
            current = false;
        };
        // `chosen` is left out on purpose: it is set here, and by choosing a person.
    }, [chosenId, registerId]);

    // The list in the popup.
    const [open, setOpen] = useState(false);
    const [searchText, setSearchText] = useState('');
    const [position, setPosition] = useState('');
    const [rows, setRows] = useState<Person[]>([]);
    const [page, setPage] = useState(1);
    const [pages, setPages] = useState(1);
    const [loading, setLoading] = useState(false);
    const [failed, setFailed] = useState(false);
    const request = useRef(0);

    const load = useCallback(
        async (text: string, positionCode: string, pageNumber: number) => {
            const mine = ++request.current;
            setLoading(true);
            setFailed(false);
            try {
                const body = await post('/api/register/records', {
                    register_id: registerId,
                    current_page: pageNumber,
                    page_size: pageSize,
                    search_text: text.trim(),
                    filter_by: positionCode ? JSON.stringify({ position: { eq: positionCode } }) : '',
                });
                if (mine !== request.current) return;
                const found = (body?.records ?? []).map(person).filter((p: Person) => p.id && p.id !== ownId);
                const total = Number(body?.pagination?.number_of_pages ?? 1);
                setRows((before) => (pageNumber === 1 ? found : [...before, ...found.filter((p: Person) => !before.some((b) => b.id === p.id))]));
                setPage(pageNumber);
                setPages(Number.isFinite(total) && total > 0 ? total : 1);
            } catch {
                if (mine !== request.current) return;
                if (pageNumber === 1) setRows([]);
                setFailed(true);
            } finally {
                if (mine === request.current) setLoading(false);
            }
        },
        [registerId, pageSize, ownId],
    );

    // Opening shows the first ten; typing or choosing a position narrows them.
    useEffect(() => {
        if (!open) return;
        const timer = setTimeout(() => load(searchText, position, 1), searchText ? 300 : 0);
        return () => clearTimeout(timer);
    }, [open, searchText, position, load]);

    // The list loads more as it is scrolled to its end. A page that does not
    // fill it (the record's own row is left out, or a filter leaves a few)
    // gives nothing to scroll, so the next page is fetched until it fills or
    // there is no more.
    const list = useRef<HTMLDivElement>(null);
    useEffect(() => {
        const box = list.current;
        if (!open || loading || failed || page >= pages || !box) return;
        if (box.scrollHeight <= box.clientHeight) load(searchText, position, page + 1);
    }, [open, loading, failed, page, pages, rows.length, searchText, position, load]);

    useEffect(() => {
        if (!open) return;
        const onKey = (event: KeyboardEvent) => {
            if (event.key === 'Escape') setOpen(false);
        };
        document.addEventListener('keydown', onKey);
        return () => document.removeEventListener('keydown', onKey);
    }, [open]);

    const openList = () => {
        setSearchText('');
        setPosition('');
        setRows([]);
        setOpen(true);
    };
    const choose = (p: Person) => {
        setChosen(p);
        setUnknown(false);
        onChange(p.id);
        setOpen(false);
    };
    const onScroll = (event: UIEvent<HTMLDivElement>) => {
        const box = event.currentTarget;
        if (!loading && page < pages && box.scrollTop + box.clientHeight >= box.scrollHeight - 24) {
            load(searchText, position, page + 1);
        }
    };

    if (isVisible === false) return null;

    const errors = Array.isArray(error) ? error : [];
    const empty = isRequired && !chosenId;
    const line = (name: string, text: string) => (
        <div className="mb-[10px] TextDisplayWidget flex flex-col sm:flex-row sm:items-start">
            <div className="text-base text-gray-600 font-medium md:min-w-[120px] sm:pr-4 mb-1 sm:mb-0 owt-field-label">{name}:</div>
            <div className="flex-1">
                <div className="text-base text-gray-900 font-medium">{text}</div>
            </div>
        </div>
    );
    const details = chosen ? (
        <>
            {line(label('reports_to_their_name'), chosen.name)}
            {line(label('reports_to_their_position'), positionName(chosen.position))}
        </>
    ) : null;

    if (readonly) {
        return (
            <div className="oan-reports-to">
                {line(title, chosenId)}
                {details}
            </div>
        );
    }

    return (
        <div className="oan-reports-to">
            <style>{`
                .oan-reports-to-box { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
                .oan-reports-to-value { min-width: 180px; height: 30px; padding: 0 12px; border: 1px solid #000; border-radius: 10px; background: #fff; text-align: left; font-size: 16px; cursor: pointer; box-shadow: 0 1px 2px rgba(0,0,0,.05); }
                .oan-reports-to-value.is-empty { color: #6b7280; }
                .oan-reports-to-value.is-missing { border-color: #dc2626; }
                .oan-reports-to-value:disabled { background: #f3f4f6; cursor: not-allowed; }
                .oan-reports-to-link { background: none; border: 0; padding: 0; font-size: 14px; text-decoration: underline; cursor: pointer; color: inherit; }
                .oan-reports-to-error { color: #dc2626; font-size: 12px; margin: 2px 0 8px; }
                .oan-reports-to-overlay { position: fixed; inset: 0; background: rgba(0,0,0,.45); z-index: 1000; display: flex; align-items: center; justify-content: center; padding: 16px; }
                .oan-reports-to-modal { background: #fff; border-radius: 12px; width: min(760px, 100%); max-height: min(620px, 90vh); display: flex; flex-direction: column; box-shadow: 0 20px 40px rgba(0,0,0,.25); color: #111827; }
                .oan-reports-to-head { padding: 16px 20px 12px; font-size: 18px; font-weight: 600; }
                .oan-reports-to-filters { display: flex; gap: 12px; padding: 0 20px 12px; flex-wrap: wrap; }
                .oan-reports-to-filters input, .oan-reports-to-filters select { height: 34px; padding: 0 10px; border: 1px solid #9ca3af; border-radius: 8px; font-size: 15px; background: #fff; }
                .oan-reports-to-filters input { flex: 1 1 220px; }
                .oan-reports-to-filters select { flex: 0 1 220px; }
                .oan-reports-to-list { overflow-y: auto; border-top: 1px solid #e5e7eb; border-bottom: 1px solid #e5e7eb; height: 372px; }
                .oan-reports-to-row, .oan-reports-to-columns { display: grid; grid-template-columns: 170px 1fr 200px; gap: 12px; padding: 0 20px; align-items: center; text-align: left; width: 100%; }
                .oan-reports-to-columns { height: 36px; font-size: 13px; font-weight: 600; color: #4b5563; background: #f3f4f6; position: sticky; top: 0; }
                .oan-reports-to-row { height: 33px; font-size: 15px; background: #fff; border: 0; border-bottom: 1px solid #f3f4f6; cursor: pointer; }
                .oan-reports-to-row:hover, .oan-reports-to-row:focus { background: #ecfdf5; outline: none; }
                .oan-reports-to-row.is-chosen { background: #d1fae5; }
                .oan-reports-to-row span, .oan-reports-to-columns span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
                .oan-reports-to-note { padding: 18px 20px; font-size: 15px; color: #4b5563; }
                .oan-reports-to-foot { padding: 12px 20px; display: flex; justify-content: flex-end; }
                .oan-reports-to-foot button { height: 34px; padding: 0 16px; border: 1px solid #000; border-radius: 8px; background: #fff; font-weight: 600; cursor: pointer; }
                @media (max-width: 640px) {
                    .oan-reports-to-row, .oan-reports-to-columns { grid-template-columns: 120px 1fr; }
                    .oan-reports-to-row span:nth-child(3), .oan-reports-to-columns span:nth-child(3) { display: none; }
                }
            `}</style>
            <div className="mb-[10px]">
                <div className="flex flex-col sm:flex-row sm:items-start">
                    <label className="flex items-baseline min-w-0 max-w-full owt-field-label text-base font-medium text-gray-700 md:min-w-[120px] sm:pr-4 sm:pt-1 mb-1 sm:mb-0">
                        <span>{title}</span>
                        {isRequired && <span style={{ color: '#dc2626', marginLeft: 4 }}>*</span>}
                    </label>
                    <div className="flex-1 min-w-0">
                        <div className="oan-reports-to-box">
                            <button
                                type="button"
                                className={`oan-reports-to-value${chosenId ? '' : ' is-empty'}${empty || unknown ? ' is-missing' : ''}`}
                                onClick={openList}
                                disabled={isEnabled === false}
                                aria-haspopup="dialog"
                            >
                                {chosenId || label('reports_to_choose')}
                            </button>
                            {chosenId && isEnabled !== false && (
                                <>
                                    <button type="button" className="oan-reports-to-link" onClick={openList}>
                                        {label('reports_to_change')}
                                    </button>
                                    <button
                                        type="button"
                                        className="oan-reports-to-link"
                                        onClick={() => {
                                            setChosen(null);
                                            setUnknown(false);
                                            onChange(null);
                                        }}
                                    >
                                        {label('reports_to_clear')}
                                    </button>
                                </>
                            )}
                        </div>
                        {unknown && <div className="oan-reports-to-error">{label('reports_to_unknown', { id: chosenId })}</div>}
                        {touched && errors.length > 0 && <div className="oan-reports-to-error">{errors.join(' ')}</div>}
                    </div>
                </div>
            </div>
            {details}
            {open && (
                <div className="oan-reports-to-overlay" onMouseDown={(e) => e.target === e.currentTarget && setOpen(false)}>
                    <div className="oan-reports-to-modal" role="dialog" aria-modal="true" aria-label={label('reports_to_title')}>
                        <div className="oan-reports-to-head">{label('reports_to_title')}</div>
                        <div className="oan-reports-to-filters">
                            <input
                                autoFocus
                                value={searchText}
                                onChange={(e) => setSearchText(e.target.value)}
                                placeholder={label('reports_to_search')}
                                aria-label={label('reports_to_search')}
                            />
                            <select value={position} onChange={(e) => setPosition(e.target.value)} aria-label={label('reports_to_position')}>
                                <option value="">{label('reports_to_all_positions')}</option>
                                {positions.map((p) => (
                                    <option key={p.code} value={p.code}>
                                        {p.name}
                                    </option>
                                ))}
                            </select>
                        </div>
                        <div className="oan-reports-to-list" ref={list} onScroll={onScroll}>
                            <div className="oan-reports-to-columns">
                                <span>{label('reports_to_id')}</span>
                                <span>{label('reports_to_name')}</span>
                                <span>{label('reports_to_position')}</span>
                            </div>
                            {rows.map((p) => (
                                <button
                                    type="button"
                                    key={p.id}
                                    className={`oan-reports-to-row${p.id === chosenId ? ' is-chosen' : ''}`}
                                    onClick={() => choose(p)}
                                >
                                    <span>{p.id}</span>
                                    <span>{p.name}</span>
                                    <span>{positionName(p.position)}</span>
                                </button>
                            ))}
                            {failed && <div className="oan-reports-to-note">{label('reports_to_failed')}</div>}
                            {!failed && !loading && rows.length === 0 && <div className="oan-reports-to-note">{label('reports_to_not_found')}</div>}
                            {loading && <div className="oan-reports-to-note">{label('reports_to_loading')}</div>}
                        </div>
                        <div className="oan-reports-to-foot">
                            <button type="button" onClick={() => setOpen(false)}>
                                {label('reports_to_cancel')}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
