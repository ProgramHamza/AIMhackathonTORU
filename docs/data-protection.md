# Data protection: what leaves the device, and why that is allowed

This app sends text to cloud models (Gemini, optionally Claude or Jina). For the hackathon the
patient is synthetic. For a hospital deployment the rules below apply; the code already
behaves as if they did.

## The legal frame (Austria)

| Rule | What it says for us | Where the code answers it |
|---|---|---|
| GDPR Art. 9 | Health data is a special category; processing needs a legal basis such as treatment (Art. 9(2)(h)) | The app is a tool for the treating clinician; it never processes data for another purpose |
| GDPR Art. 5(1)(c), 25 | Data minimisation and data protection by design | Only the passages a task needs are sent, never whole records; identifiers are removed first |
| GDPR Art. 4(5), Recital 26 | Replacing identifiers is *pseudonymisation*; the data stays personal data (a key could re-identify it) | We call it de-identification, not anonymisation, and keep every other safeguard |
| GDPR Art. 28 | A cloud model provider is a processor and needs a contract (DPA), with no use of the data for its own purposes | Free API tiers do not offer this: a deployment needs a paid/enterprise tier with a DPA and no-training terms |
| GDPR Art. 32 | Security appropriate to the risk; encryption and pseudonymisation are named explicitly | TLS in transit (HTTPS is enforced), AES-256-GCM at rest for every cache, pseudonymisation before any call |
| GDPR Art. 35 | A DPIA for large-scale processing of health data with new technology | Required before a real deployment; this document is input to it |
| GDPR Art. 44–46 | Transfers outside the EU need an adequacy decision or standard contractual clauses | US providers: the EU–US Data Privacy Framework is in force but contested in 2026; prefer EU-region endpoints and keep an exit plan |
| GTelG 2012 § 3(4) | Health service providers may transmit health data only where Art. 9 GDPR allows it | Same basis as above |
| GTelG 2012 § 6(1)–(3) | Transmission and cloud storage of health data only with state-of-the-art full encryption; unencrypted parts must not point to the person | HTTPS only; encrypted caches; identifiers removed from everything sent |
| GTelG 2012 § 8 | An IT security concept for health service providers | The gate, the key handling and this document are the first entries |
| ÄrzteG § 54, KAKuG § 10 | Medical confidentiality; documentation duties stay with the hospital | The app changes no record; it reads and links |

Sources checked on 30 Oct 2026: the GTelG 2012 text on RIS (§ 3, § 6, § 27 transition rules)
and the GDPR articles above. The Data Privacy Framework status is from EDPB/press material of
mid-2026 and should be re-checked before a deployment decision.

## What the code does

1. **One gate for everything that leaves the device** (`app/outbound.py`). Every provider
   client passes its text through it. There is no second path to the network.
2. **De-identification** (`app/deidentify.py`): names of patient and clinicians, birth date (all
   formats), patient / case / social-security numbers, addresses, phone numbers and e-mails,
   facility names and the place in letter heads are replaced by fixed tokens such as `[NAME]`.
   The gate is configured per patient from `patient.json` and `documents.json`, so the real
   name and birth date are matched exactly, in addition to the generic patterns.
3. **Refuse rather than leak**: after scrubbing, a second check looks for direct identifiers.
   If any is left, the call is refused (`PHILeakError`) and nothing is sent. The result then
   falls back to templates or the keyword path.
4. **What stays in the text**: dates of care, ages, values, units, drug names. The clinician's
   questions ("latest value", "did this happen before") need them. This is the residual risk
   of pseudonymised data and the reason the other safeguards (contract, region, encryption,
   access control) remain necessary.
5. **Encryption at rest** (`app/vault.py`): the remarker index, embedding caches, summary
   cache and prompt-analysis cache are AES-256-GCM encrypted. A copied `.cache` folder is
   useless without the key (`DATA_KEY` or `backend/.cache/.data_key`). Tampered files are
   detected, not read.
6. **HTTPS only** for any non-local endpoint; local Ollama is exempt because nothing leaves
   the machine.
7. **Transparency**: every result carries `privacy` statistics (how many identifiers were
   replaced per call type, how many calls were refused), so a reviewer can see the gate at work.

## What this does not do

- It does not make the data anonymous. Rare combinations of dates and findings can still
  identify a person. Treat the cloud provider as a processor, in the EU where possible.
- It does not replace access control, logging and a DPIA in the hospital.
- It cannot catch a name that appears without any of the known patterns (for example a
  nickname inside free text). The patient-specific configuration covers the names the system
  knows about; a hospital deployment should feed it the full identity record.
