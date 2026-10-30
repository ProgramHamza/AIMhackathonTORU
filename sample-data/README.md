# Sample data

An invented patient (Eva Probst, born 1957) in the same folder format as the challenge data: `patient.json`, `documents.json` and `documents/<id>.json` with `metadata` and `text` (line breaks as `<BR>`).
Nothing here comes from the challenge dataset, which is not part of this repository.

    cd backend && python -m app.server --patient ../sample-data/patient-9001-0001

The record contains three deliberate contradictions: the side of the knee operation (right / left), a penicillin allergy against "Allergien: keine bekannt", and a BMI of 25 that does not match 79 kg at 164 cm.
