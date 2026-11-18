'use client';

import { createElement, useEffect, useId, useMemo, useRef, useState } from 'react';
import { useSelector } from 'react-redux';
import { GeoHierarchyWidget, getValueByPath, useBaseWidget, useWidgetContext, type WidgetRootState } from '@openg2p/registry-widgets';

type Config = Record<string, any>;
type Level = { level_id: string; level_mnemonic: string; parent_level_id: string | null };
type Rule = { field: string; levels?: Record<string, string>; default?: string };

const NONE = 'none';

const LABELS: Record<string, string> = {
    work_location_not_needed: 'No work location is needed for this position.',
    work_location_down_to: 'Choose the location down to the {level}.',
};

// The Master Data levels, from the root down, asked once per page.
let levelsRequest: Promise<Level[]> | null = null;

function rows(response: unknown): unknown[] {
    if (Array.isArray(response)) return response;
    const body = (response ?? {}) as Config;
    if (Array.isArray(body.response_payload)) return body.response_payload;
    if (Array.isArray(body.response_body?.response_payload)) return body.response_body.response_payload;
    return [];
}

type Entry = Record<string, any>;

function entriesOf(chain: unknown): Entry[] {
    if (Array.isArray(chain)) return chain as Entry[];
    const hierarchy = (chain as Config | null)?.hierarchy;
    return Array.isArray(hierarchy) ? hierarchy : [];
}

const levelOf = (entry: Entry) => String(entry?.level_mnemonic ?? entry?.level ?? '').toLowerCase();

/** The chain down to `level`, in the shape it was stored in; null when it does not go deeper. */
function cutChain(chain: unknown, level: string): { value: string; hierarchy: unknown } | null {
    const entries = entriesOf(chain);
    const at = entries.findIndex((entry) => levelOf(entry) === level);
    if (at < 0 || at === entries.length - 1) return null;
    const kept = entries.slice(0, at + 1);
    const value = String(kept[at]?.level_value_id ?? '');
    const hierarchy = Array.isArray(chain) ? kept : { ...(chain as Config), hierarchy: kept, lowest_level_value_id: value };
    return { value, hierarchy };
}

function ordered(flat: Level[]): Level[] {
    const out: Level[] = [];
    let current = flat.find((level) => !level.parent_level_id);
    const seen = new Set<string>();
    while (current && !seen.has(current.level_id)) {
        seen.add(current.level_id);
        out.push(current);
        const parent: string = current.level_id;
        current = flat.find((level) => level.parent_level_id === parent);
    }
    return out;
}

/**
 * The Work location, as far down as the person's position needs it.
 *
 * It is the platform's geo widget, registered under its own type
 * ("geo-hierarchy"), and takes over only where the widget carries
 * "oan-location-depth" (95_work_location.sql):
 *
 *   {"field": "<register>.position",
 *    "levels": {"SUPERVISOR": "woreda", "ADMIN": "none", ...},
 *    "default": "kebele"}
 *
 * - a position whose level is "none" (an administrator, a communication
 *   officer) has no Work location: a line says so instead of the boxes;
 * - a position whose level is above the last one (a supervisor: the Woreda)
 *   sees the boxes down to that level only; the platform's widget saves the
 *   deepest one chosen;
 * - every other position (a development agent) sees them all, and every one
 *   must be filled.
 *
 * When the position changes after the location was filled in (a development
 * agent made an administrator, or a supervisor), what the new position does
 * not take is taken off the form at once: the whole location, or the levels
 * below the position's one. The API does the same with what is saved
 * (location_depth.py): it leaves out what goes deeper than the position's
 * level, and refuses a location that stops above it.
 */
export function GeoByPositionWidget(props: { config: Config } & Config) {
    const { config } = props;
    const rule = config['oan-location-depth'] as Rule | undefined;
    const { t, schemaData, dataSourceRequestHandler } = useWidgetContext();
    const values = useSelector((state: WidgetRootState) => state.widget.values);
    const scope = useId().replace(/[^a-zA-Z0-9_-]/g, '');
    const [levels, setLevels] = useState<Level[]>([]);
    // Bumped when this widget rewrites the stored location, so the platform's
    // widget starts again from it (it keeps its own copy of the choices).
    const [epoch, setEpoch] = useState(0);
    const base = useBaseWidget({ config: config as never }) as { onChange: (value: unknown) => void };
    const dataPath = config['widget-data-path'] as Config | string | undefined;
    const valuePath = typeof dataPath === 'object' ? String(dataPath?.value ?? '') : String(dataPath ?? '');
    const hierarchyPath = typeof dataPath === 'object' ? String(dataPath?.hierarchy ?? '') : '';

    const label = (key: string, params: Record<string, string> = {}) => {
        const fallback = (LABELS[key] ?? key).replace(/\{(\w+)\}/g, (_m, name) => params[name] ?? '');
        const text = t ? t(key, { defaultValue: fallback, ...params }) : fallback;
        // A key with no translation comes back as itself: show the English text.
        return !text || text === key ? fallback : text;
    };

    const field = rule?.field ?? '';
    const inForm = field ? getValueByPath(values, field) : undefined;
    const position = String(
        (inForm !== undefined && inForm !== null && inForm !== '' ? inForm : field ? getValueByPath(schemaData ?? {}, field) : '') ?? '',
    );
    const depth = String((position && rule?.levels?.[position]) || rule?.default || '').toLowerCase();

    const source = config['widget-data-source'] as Config | undefined;
    useEffect(() => {
        if (!rule || !source?.levelsEndpoint || !dataSourceRequestHandler) return;
        let active = true;
        if (!levelsRequest) {
            levelsRequest = Promise.resolve(
                dataSourceRequestHandler(source.service, source.levelsEndpoint, source.method || 'POST', {
                    current_page: 1,
                    page_size: 100,
                }),
            )
                .then((response) => ordered(rows(response) as Level[]))
                .catch(() => {
                    levelsRequest = null;
                    return [];
                });
        }
        levelsRequest.then((found) => {
            if (active) setLevels(found);
        });
        return () => {
            active = false;
        };
    }, [rule, source?.service, source?.levelsEndpoint, dataSourceRequestHandler]);

    const index = levels.findIndex((level) => level.level_mnemonic.toLowerCase() === depth);
    const cut = index >= 0 && index < levels.length - 1;
    const required = !cut;

    // Fit what the form holds to the position: nothing for "none", the chain
    // down to the position's level otherwise.
    const storedValue = valuePath ? getValueByPath(values, valuePath) : undefined;
    const storedChain = hierarchyPath ? getValueByPath(values, hierarchyPath) : undefined;
    const lastFit = useRef('');
    useEffect(() => {
        if (!rule || config['widget-readonly'] || !position) return;
        const key = `${depth}|${String(storedValue ?? '')}`;
        if (lastFit.current === key) return;
        lastFit.current = key;
        if (depth === NONE) {
            if (storedValue || storedChain) {
                base.onChange(hierarchyPath ? { value: null, hierarchy: null } : null);
                setEpoch((n) => n + 1);
            }
            return;
        }
        const fitted = storedChain ? cutChain(storedChain, depth) : null;
        if (fitted) {
            base.onChange(hierarchyPath ? fitted : fitted.value);
            setEpoch((n) => n + 1);
        }
    }, [rule, depth, position, storedValue, storedChain, hierarchyPath]);

    // Required while every level is to be filled; for a position that stops
    // above the last level the platform's widget must save a partial chain,
    // which it does only when the widget is not required.
    const inner = useMemo(() => ({ ...config, 'widget-required': required }), [config, required]);

    if (!rule) return createElement(GeoHierarchyWidget as never, props as never);
    if (depth === NONE) {
        return createElement('p', { className: 'text-sm owt-text-muted mb-[10px]' }, label('work_location_not_needed'));
    }
    const widget = createElement(GeoHierarchyWidget as never, { ...props, config: inner, key: `${depth}-${epoch}` } as never);
    if (!cut || config['widget-readonly']) return widget;
    // The boxes below the position's level are hidden: one box per level, in
    // order, under the widget's root (one column, widget-geo-layout.columnSpan 1).
    // The levels shown are all required, so each label gets the platform's red
    // star (the platform's widget is told it is not required, see `inner`).
    const step = `[data-oan-geo="${scope}"] .GeoHierarchyWidget > div.mb-\\[10px\\]`;
    const css =
        `${step}:nth-child(n+${index + 2}) { display: none !important; } ` +
        `${step} label.owt-field-label::after { content: '*'; margin-left: 0.25rem; ` +
        'color: var(--owt-widget-error-color); }';
    const name = String(levels[index]?.level_mnemonic ?? depth);
    const hint = name.charAt(0).toUpperCase() + name.slice(1);
    return createElement(
        'div',
        { 'data-oan-geo': scope },
        createElement('style', null, css),
        createElement('p', { className: 'text-sm owt-text-muted mb-[10px]' }, label('work_location_down_to', { level: hint })),
        widget,
    );
}
