import { createElement } from 'react';
import { HeaderSectionWidget, widgetRegistry } from '@openg2p/registry-widgets';
import { FileListCellWidget } from './FileListCellWidget';
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
