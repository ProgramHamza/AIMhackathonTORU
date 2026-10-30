"""Conservative source-date checks; never repair an invalid date."""
import re
from datetime import date

MONTHS = {name: i + 1 for i, name in enumerate(
    ('januar', 'februar', 'märz', 'april', 'mai', 'juni', 'juli', 'august',
     'september', 'oktober', 'november', 'dezember'))}
VERSION = 'source-checks-v3'


def source_dates(text):
    found = set()
    for m in re.finditer(r'(?<!\d)(\d{1,2})[./](\d{1,2})[./](\d{4})(?!\d)', text):
        try:
            found.add(date(int(m[3]), int(m[2]), int(m[1])).isoformat())
        except ValueError:
            pass
    for m in re.finditer(r'(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)', text):
        try:
            found.add(date.fromisoformat(m[0]).isoformat())
        except ValueError:
            pass
    for m in re.finditer(r'(?<!\d)(\d{1,2})\.?\s+(' + '|'.join(MONTHS) + r')\s+(\d{4})(?!\d)', text, re.I):
        try:
            found.add(date(int(m[3]), MONTHS[m[2].lower()], int(m[1])).isoformat())
        except ValueError:
            pass
    return found


def check_time(time, quotes, document):
    if time.anchor_fact_id is not None:
        raise ValueError('external_anchor_not_allowed')
    if time.precision == 'unknown':
        return
    if time.basis == 'document_fallback':
        if document.document_date is None or time.precision != 'day' or time.value != document.document_date.isoformat():
            raise ValueError('incorrect_document_date_fallback')
        return
    text = '\n'.join(quotes)
    if time.original_text and time.original_text not in text:
        raise ValueError('date_original_text_not_cited')
    days = source_dates(text)
    if time.precision in ('day', 'interval'):
        if time.value not in days or (time.end and time.end not in days):
            raise ValueError('date_not_supported_by_cited_valid_date')
        if time.original_text and time.value not in source_dates(time.original_text):
            raise ValueError('original_date_does_not_support_normalized_value')
    elif time.precision == 'month':
        year, month = time.value.split('-')
        pattern = rf'(?<![\d./-])0?{int(month)}[./]{year}(?!\d)|(?<!\d){year}-{month}(?![\d-])'
        if not any(d.startswith(time.value) for d in days) and not re.search(pattern, text):
            raise ValueError('month_not_supported_by_citation')
    elif time.precision == 'year':
        if not re.search(r'(?<!\d)' + re.escape(time.value) + r'(?!\d)', text):
            raise ValueError('year_not_supported_by_citation')
    elif time.precision == 'relative':
        if not time.original_text or time.original_text not in text:
            raise ValueError('relative_time_requires_cited_original_text')


def check_status(candidate, quotes):
    if candidate.clinical_status == 'completed' and candidate.value.kind != 'event':
        raise ValueError('completed_requires_event_payload_use_unknown_for_findings')
    if candidate.clinical_status == 'resolved':
        if not re.search(r'\b(nicht mehr|abgeklungen|verschwunden|resolved)\b', '\n'.join(quotes), re.I):
            raise ValueError('absence_is_not_resolution_use_unknown_status')


def check_measurement(candidate, quotes):
    if candidate.value.kind != 'measurement':
        return
    numbers = {float(m[0].replace(',', '.')) for m in re.finditer(r'(?<![\d.,])\d+(?:[.,]\d+)?(?![\d.,])', '\n'.join(quotes))}
    if candidate.value.quantity.value not in numbers:
        raise ValueError('measurement_not_verbatim_use_original_assertion_no_calculations')
