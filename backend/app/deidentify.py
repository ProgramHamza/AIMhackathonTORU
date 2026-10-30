"""De-identification of clinical text before it leaves the device.

What is removed (replaced by a fixed token, so the model still sees that something was
there): patient and clinician names, date of birth, patient / case / social-security
numbers, addresses, phone numbers, facility names and the place in letter headers.

What stays: clinical content, including dates of care, ages, values and units. The
clinician needs the dates to answer "latest value" and "did it happen before" questions.
Under the GDPR this is pseudonymisation (Art. 4(5)), not anonymisation (Recital 26): the
text stays personal data, and the cloud provider stays a processor (Art. 28) that must be
contracted and may only see what the task needs (Art. 5(1)(c), 9, 32). See
docs/data-protection.md.

Two layers:
  scrub(text)  rewrites the text (generic patterns + everything known about the patient).
  leaks(text)  lists direct identifiers that are still present. The outbound gate calls it
               after scrub and refuses to send if anything is found.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date

TOKENS = ("NAME", "DOB", "ID", "CASE", "ADDRESS", "CLINICIAN", "FACILITY", "PHONE", "PLACE", "SVNR", "EMAIL")

_MONTHS = ("januar|februar|märz|maerz|april|mai|juni|juli|august|september|oktober|november|dezember|"
           "jänner|january|february|march|may|june|july|october|december|jan|feb|mär|apr|jun|jul|aug|sep|sept|okt|nov|dez|oct|dec")
_TITLES = r"(?:Prim(?:ar(?:ia|ius)?)?|O[AÄ]|Dr|DDr|Univ\.?-?\s?Prof|Prof|Priv\.?-?Doz|Ass(?:\.?-?Prof)?|Mag|MUDr|MD|Hofrat|Med\.?\s?Rat)"
_CAP = r"[A-ZÄÖÜ][\wäöüß'’.-]*"

GENERIC: list[tuple[re.Pattern, str]] = [
    # explicit date of birth, any format, with its label
    (re.compile(r"\b(geb(?:oren|\.)?|born|DOB|Geburtsdatum|date of birth)\s*(am\s*)?:?\s*"
                r"(\d{1,2}[./]\s?\d{1,2}[./]\s?\d{2,4}|\d{4}-\d{2}-\d{2}|\d{1,2}\.?\s+(?:" + _MONTHS + r")\.?\s+\d{4})",
                re.IGNORECASE), r"\1 [DOB]"),
    # pseudonymous patient identifiers as used in Austrian hospital exports
    (re.compile(r"\b(?:NN|VN)_[\w-]+"), "[ID]"),
    (re.compile(r"\b(Patient(?:en)?-?\s?(?:ID|Nr\.?|Nummer)|Patient\s?ID|MRN)\s*:?\s*[\w/-]+", re.IGNORECASE), r"\1: [ID]"),
    (re.compile(r"\b(Beispielpatient(?:in)?|Musterpatient(?:in)?|Testpatient(?:in)?)\b", re.IGNORECASE), "[NAME]"),
    # case / encounter numbers
    (re.compile(r"\b(Fall(?:zahl|-?ID|-?Nr\.?|nummer)?|Aufnahmezahl|Aufnahme-?Nr\.?|Case(?:\s?(?:no\.?|number|ID))?)\s*:?\s*\d{6,}\b",
                re.IGNORECASE), r"\1: [CASE]"),
    # Austrian social security number: 4 + 6 digits (the last six are the birth date)
    (re.compile(r"\b(SVNR|SV-?Nr\.?|Versicherungsnummer|Sozialversicherungsnummer)\s*:?\s*\d{4}\s?\d{6}\b", re.IGNORECASE), r"\1: [SVNR]"),
    (re.compile(r"\b\d{4}\s\d{6}\b"), "[SVNR]"),
    # contact data
    (re.compile(r"[\w.+\[\]-]+@[\w-]+\.[\w.-]+"), "[EMAIL]"),
    (re.compile(r"\b(Tel\.?|Telefon|Phone|Mobil|Fax|DW)\s*\.?:?\s*(?:\+?\d[\d /()-]{3,})", re.IGNORECASE), r"\1: [PHONE]"),
    (re.compile(r"(/\s*Tel\.?:?\s*)\d[\d /()-]*", re.IGNORECASE), r"\1[PHONE]"),
    # "Tel.: Arzt / 0032": the number at the end of a contact line
    (re.compile(r"(\bTel\.?:?[^\n]*?/\s*)(\d[\d /()-]{2,})(?=\s*$)", re.IGNORECASE | re.MULTILINE), r"\1[PHONE]"),
    # addresses: street lines, "PLZ Ort" placeholders, Austrian postcode + town
    # a street: capitalised name ending in a street word, then a house number or a placeholder
    # like "XY/AB". Case-sensitive on purpose: "glucose-lowering", "during", "Atemwege" are not streets.
    (re.compile(r"\b(?:[A-ZÄÖÜ][\wäöüß-]*(?:straße|strasse|str\.|gasse|platz|weg|allee|ring)|Straße|Strasse|Str\.|Gasse|Platz|Weg|Allee|Ring)"
                r"[ \t]+(?:\d+[a-z]?(?:[ \t]*/[ \t]*\d+[a-z]?)*|[A-Z]{1,3}[ \t]*/[ \t]*[A-Z]{1,3})(?![\wäöüß])"), "[ADDRESS]"),
    (re.compile(r"\bPLZ\s+\S+"), "[ADDRESS]"),
    (re.compile(r"\b(?!(?:19|20)\d{2}\b)\d{4}\s+[A-ZÄÖÜ][a-zäöüß]{2,}(?:\s(?:am|an|bei|im)\s[A-ZÄÖÜ][a-zäöüß]+)?\b"), "[ADDRESS]"),
    # clinician names after titles or signature labels
    (re.compile(r"\b" + _TITLES + r"\.?[ \t]+(?:med\.?[ \t]+)?(?:univ\.?[ \t]+)?" + _CAP + r"(?:[ \t]+" + _CAP + r"){0,4}\.?"), "[CLINICIAN]"),
    (re.compile(r"\b(befundet|vidiert|Befund|Zuweiser|Zuweisung freigegeben durch|diktiert|erstellt|Arzt|Ärztin|signed by|reported by)"
                r"([ \t]*(?:/[ \t]*Tel\.?)?[ \t]*:[ \t]*|[ \t]+)((?:" + _TITLES + r"\.?[ \t]+)?" + _CAP + r"(?:[ \t]+" + _CAP + r"){0,2})(?=[ \t]*$|[ \t]*[/|,;]|\n)",
                re.IGNORECASE | re.MULTILINE), r"\1\2[CLINICIAN]"),
    (re.compile(r"\b(ARZT|AERZTIN|ÄRZTIN)\s+[A-Z]{1,4}\b"), "[CLINICIAN]"),
    # facilities
    (re.compile(r"\b[\wäöüß-]*(?:Krankenhaus|Krankenanstalt|Klinikum|Klinik|Spital|Landeskrankenhaus|Universitätsklinik|Ordination)\b"
                r"(?:\s+(?:der\s+)?[A-ZÄÖÜ][\wäöüß.-]*){0,3}"), "[FACILITY]"),
    # letter head "Ort, am 12.06.2015" with real or placeholder place names
    (re.compile(r"^(\s*)(?:[A-ZÄÖÜ][\wäöüß.-]*|X{2,}|Ort[A-Za-z]*|ORT[A-Z]*),?\s+(am\s+\d{1,2}\.\d{1,2}\.\d{4})", re.MULTILINE), r"\1[PLACE], \2"),
]

# Direct identifiers that must never survive scrub (checked again by the gate).
STRONG_LEAKS: list[re.Pattern] = [
    re.compile(r"\b(?:NN|VN)_[\w-]+"),
    re.compile(r"\b(geb(?:oren|\.)?|born|DOB)\s*(am\s*)?:?\s*\d{1,2}[./]\d{1,2}[./]\d{2,4}", re.IGNORECASE),
    re.compile(r"\b\d{4}\s\d{6}\b"),
    re.compile(r"[\w.+\[\]-]+@[\w-]+\.[\w.-]+"),
    re.compile(r"\b(Beispielpatient(?:in)?|Musterpatient(?:in)?)\b", re.IGNORECASE),
]

_DATE_FMTS = ("%d.%m.%Y", "%d/%m/%Y", "%Y-%m-%d", "%d.%m.%y", "%-d.%-m.%Y")
_MONTH_NAMES_DE = ["Jänner", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September",
                   "Oktober", "November", "Dezember"]
_MONTH_NAMES_EN = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
                   "October", "November", "December"]


def _dob_variants(dob: date) -> list[str]:
    out = {dob.strftime("%d.%m.%Y"), dob.strftime("%d/%m/%Y"), dob.isoformat(), dob.strftime("%d.%m.%y"),
           f"{dob.day}.{dob.month}.{dob.year}", f"{dob.day}. {dob.month}. {dob.year}",
           dob.strftime("%m/%d/%Y"), dob.strftime("%d-%m-%Y"),
           f"{dob.day}. {_MONTH_NAMES_DE[dob.month - 1]} {dob.year}",
           f"{dob.day} {_MONTH_NAMES_EN[dob.month - 1]} {dob.year}",
           f"{_MONTH_NAMES_EN[dob.month - 1]} {dob.day}, {dob.year}",
           f"{dob.day}. {_MONTH_NAMES_DE[dob.month - 1][:3]}. {dob.year}"}
    if dob.month == 1:
        out.add(f"{dob.day}. Januar {dob.year}")
    return sorted(out, key=len, reverse=True)


@dataclass
class ScrubResult:
    text: str
    replaced: Counter = field(default_factory=Counter)

    @property
    def changed(self) -> bool:
        return sum(self.replaced.values()) > 0


class Deidentifier:
    def __init__(self, names: list[str] | tuple[str, ...] = (), dob: date | None = None,
                 ids: list[str] | tuple[str, ...] = (), facilities: list[str] | tuple[str, ...] = (),
                 clinicians: list[str] | tuple[str, ...] = (), extra: dict[str, list[str]] | None = None) -> None:
        self.known: list[tuple[re.Pattern, str]] = []
        self.strong: list[re.Pattern] = []

        def add(values, token, strong=False, flags=re.IGNORECASE):
            vals = sorted({v.strip() for v in values if v and len(v.strip()) >= 2}, key=len, reverse=True)
            if not vals:
                return
            rx = re.compile(r"(?<![\wäöüß])(?:" + "|".join(re.escape(v) for v in vals) + r")(?![\wäöüß])", flags)
            self.known.append((rx, f"[{token}]"))
            if strong:
                self.strong.append(rx)

        name_parts = []
        for n in names:
            name_parts.append(n)
            name_parts += [p for p in re.split(r"[\s,-]+", n) if len(p) >= 3]
        add(name_parts, "NAME", strong=True)
        if dob:
            add(_dob_variants(dob), "DOB", strong=True, flags=0)
        add(ids, "ID", strong=True, flags=0)
        add(facilities, "FACILITY")
        add(clinicians, "CLINICIAN", strong=True)
        for token, values in (extra or {}).items():
            add(values, token.upper(), strong=True)

    # ------------------------------------------------------------------------
    def scrub(self, text: str) -> ScrubResult:
        if not text:
            return ScrubResult(text)
        counts: Counter = Counter()
        out = text
        for rx, repl in self.known + GENERIC:
            out, n = rx.subn(repl, out)
            if n:
                token = re.search(r"\[([A-Z]+)\]", repl)
                counts[token.group(1) if token else "?"] += n
        return ScrubResult(out, counts)

    def leaks(self, text: str) -> list[str]:
        """Direct identifiers still present in `text` (empty list = safe to send)."""
        if not text:
            return []
        hits: list[str] = []
        for rx in self.strong + STRONG_LEAKS:
            for m in rx.finditer(text):
                hits.append(m.group(0))
        return hits

    # ------------------------------------------------------------------------
    @classmethod
    def for_patient(cls, patient: dict | None, documents: list[dict] | None = None,
                    extra: dict[str, list[str]] | None = None) -> "Deidentifier":
        """Everything we know about the patient from patient.json and documents.json."""
        patient = patient or {}
        names = [patient.get("name", "")]
        dob = None
        if patient.get("dateOfBirth"):
            try:
                dob = date.fromisoformat(str(patient["dateOfBirth"])[:10])
            except ValueError:
                dob = None
        ids = [str(patient.get("id", ""))] if patient.get("id") else []
        facilities, clinicians = [], []
        for d in documents or []:
            for key in ("hospital", "department", "division"):
                if d.get(key):
                    facilities.append(str(d[key]))
            for key in ("author", "physician", "signedBy"):
                if d.get(key):
                    clinicians.append(str(d[key]))
        return cls(names=names, dob=dob, ids=ids, facilities=facilities, clinicians=clinicians, extra=extra)


DEFAULT = Deidentifier()  # generic patterns only; the pipeline configures a patient-specific one
