import { createElement } from 'react';
import { HeaderSectionWidget, widgetRegistry } from '@openg2p/registry-widgets';
import { FileListCellWidget } from './FileListCellWidget';
import { RecordFilesTableWidget } from './RecordFilesTableWidget';
import { PROFILE_PHOTO_VARIANT, ProfilePhotoWidget } from './ProfilePhotoWidget';

// The widget package uploads a section's photo, and sets the field named by
// the widget's "image" path (record_image_document_id), only for widgets of
// type "header-section" (sectionFiles.ts). The profile photo keeps that type in
// the section metadata so its upload takes that route, and is told apart by
// "widget-variant". Every other header-section is upstream's widget, unchanged.
type Props = { config: Record<string, unknown> } & Record<string, unknown>;

function HeaderSectionOrVariant(props: Props) {
    if (props.config['widget-variant'] === PROFILE_PHOTO_VARIANT) {
        return createElement(ProfilePhotoWidget, props);
    }
    return createElement(HeaderSectionWidget, props as never);
}

widgetRegistry.register({ widget: 'header-section', component: HeaderSectionOrVariant });

// OAN's own widget type: several files in one table cell (the certificates of
// an education & professional record). A table cell widget gets the cell value
// and onChange from the table.
widgetRegistry.register({ widget: 'oan-file-list-cell', component: FileListCellWidget as never });

// The platform's table shows a row's files as the text "Attached". The same
// table, with the rows' files listed under it and a View button each; a table
// without a file column is upstream's, unchanged. See RecordFilesTableWidget.
widgetRegistry.register({ widget: 'dialog-table', component: RecordFilesTableWidget as never });

// A date picker opened inside an "Add record" dialog: the dialog's field grid
// scrolls (overflow: auto), so the calendar, which drops below its box, was cut
// off at the grid's edge and only its first line, or nothing, showed. While a
// calendar is open the grid lets it overflow; otherwise it scrolls as before.
const DIALOG_CALENDAR_STYLE_ID = 'oan-dialog-calendar';
if (typeof document !== 'undefined' && !document.getElementById(DIALOG_CALENDAR_STYLE_ID)) {
    const style = document.createElement('style');
    style.id = DIALOG_CALENDAR_STYLE_ID;
    style.textContent =
        '.dialog-table-modal .overflow-auto:has(.absolute.z-50) { overflow: visible !important; }';
    document.head.appendChild(style);
}

// Home address (96_home_address.sql) has a row of its own, as wide as the phone
// and email columns together. A section gives every label half of its row, so
// the address box started in the middle of the section, away from the boxes
// above it, and kept the platform's 180px, which shows about 16 characters of
// a 100-character address. Here the label is as wide as a label in the phone
// column (a quarter of the row, less the 40px each column keeps to its
// divider), and the box runs from there to the end of the row. Narrow screens
// stack label and box, as the platform does.
const HOME_ADDRESS_STYLE_ID = 'oan-home-address';
if (typeof document !== 'undefined' && !document.getElementById(HOME_ADDRESS_STYLE_ID)) {
    const field = '[data-widget-id="address_line_1"]';
    const label = `${field} .owt-field-label.owt-field-label.owt-field-label`;
    const labelWidth = 'calc((100% - 80px) / 4)';
    const style = document.createElement('style');
    style.id = HOME_ADDRESS_STYLE_ID;
    style.textContent =
        `@media (min-width: 640px) { ${label} { width: ${labelWidth} !important; ` +
        `min-width: ${labelWidth} !important; max-width: ${labelWidth} !important; } } ` +
        `${field} input { width: 100% !important; }`;
    document.head.appendChild(style);
}
