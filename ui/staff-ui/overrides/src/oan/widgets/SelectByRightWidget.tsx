'use client';

import { createElement, useEffect, useState } from 'react';
import { useSelector } from 'react-redux';
import { SelectWidget, getValueByPath, useWidgetContext, type WidgetRootState } from '@openg2p/registry-widgets';

type Config = Record<string, any>;
type Option = { value: string; label: string };

// The signed-in user's permissions for this application, asked once per page.
let permissionsRequest: Promise<Set<string>> | null = null;
function userPermissions(): Promise<Set<string>> {
    if (!permissionsRequest) {
        permissionsRequest = fetch('/api/permissions', { credentials: 'include', cache: 'no-store' })
            .then((response) => (response.ok ? response.json() : []))
            .then((body) => {
                const found = new Set<string>();
                const take = (node: unknown) => {
                    if (typeof node === 'string') found.add(node);
                    else if (Array.isArray(node)) node.forEach(take);
                    else if (node && typeof node === 'object') take((node as Config).permissions);
                };
                take(body);
                return found;
            })
            .catch(() => new Set<string>());
    }
    return permissionsRequest;
}

async function listValues(source: Config): Promise<Option[]> {
    const { withCsrfHeaders } = await import('@/shared/utils/csrf');
    const response = await fetch('/api/attributes/values', {
        method: 'POST',
        headers: withCsrfHeaders('POST', { 'Content-Type': 'application/json' }),
        credentials: 'include',
        body: JSON.stringify({ ...(source.params ?? {}) }),
    });
    if (!response.ok) throw new Error(String(response.status));
    const rows = await response.json();
    const valueKey = source.valueKey ?? 'value_id';
    const labelKey = source.labelKey ?? 'value_display';
    return (Array.isArray(rows) ? rows : []).map((row: Config) => ({
        value: String(row[valueKey] ?? ''),
        label: String(row[labelKey] ?? row[valueKey] ?? ''),
    }));
}

/**
 * A dropdown that offers some of its values only to users who may give them.
 * It is the platform's select; for a user without the permission the list is
 * cut down to the open values (and the value the record already has, so it
 * still shows).
 *
 * Metadata:
 *   widget: "oan-select-by-right"
 *   widget-data-source: the Master Data list, as for a select
 *   oan-value-rights: {open: [values anyone may give], permission: "<permission>"}
 *
 * This only keeps the choice off the screen. The API refuses the value from a
 * user who may not give it (position_rights.py), whatever the form shows.
 */
export function SelectByRightWidget(props: { config: Config }) {
    const { config } = props;
    const { schemaData } = useWidgetContext();
    const values = useSelector((state: WidgetRootState) => state.widget.values);
    const rights = config['oan-value-rights'] as { open?: string[]; permission?: string } | undefined;
    const source = config['widget-data-source'] as Config | undefined;
    const path = typeof config['widget-data-path'] === 'string' ? (config['widget-data-path'] as string) : '';
    const inForm = path ? getValueByPath(values, path) : undefined;
    const current = String((inForm !== undefined ? inForm : path ? getValueByPath(schemaData ?? {}, path) : '') ?? '');
    const limited = !config['widget-readonly'] && !!rights?.permission && Array.isArray(rights?.open) && source?.type === 'api';

    // undefined: not known yet; null: the whole list; else the cut-down list.
    const [options, setOptions] = useState<Option[] | null | undefined>(limited ? undefined : null);
    useEffect(() => {
        if (!limited) {
            setOptions(null);
            return;
        }
        let active = true;
        userPermissions()
            .then(async (permissions) => {
                if (permissions.has(String(rights?.permission))) return null;
                const keep = new Set<string>([...(rights?.open ?? []).map(String)]);
                return (await listValues(source as Config)).filter((o) => keep.has(o.value) || o.value === current);
            })
            // If the list cannot be had, show the platform's own; the API still decides.
            .catch(() => null)
            .then((found) => {
                if (active) setOptions(found);
            });
        return () => {
            active = false;
        };
        // The value the record had when the form opened is enough; a later choice is in the list already.
    }, [limited, rights?.permission, source?.params?.attribute_id]);

    if (options === undefined) return null;
    if (options === null) return createElement(SelectWidget as never, props as never);
    // Its own id, so the options the full list cached under the field's id are not used.
    const narrowed = {
        ...config,
        'widget-id': `${config['widget-id']}__by_right`,
        'widget-data-source': { type: 'static', options },
    };
    return createElement(SelectWidget as never, { ...props, config: narrowed } as never);
}
