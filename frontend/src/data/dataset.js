import { patient as synPatient } from './patient';
import { encounter as synEncounter } from './encounter';
import { documents as synDocuments } from './documents';
import { makeDocumentStore } from '../lib/sources';

/**
 * Bundled fixtures. The hackathon patient comes from the backend (lib/backend.js), so no
 * patient data is embedded in a build; the fictional patient stays for offline UI checks.
 */
const synthetic = {
  key: 'synthetic',
  note: 'Fictional demo patient',
  patient: synPatient,
  encounter: synEncounter,
  documents: synDocuments,
  store: makeDocumentStore(synDocuments),
  tasks: [{ id: 'preop', label: 'Pre-operative assessment before cholecystectomy', role: 'Anaesthesiologist', curated: true }],
};

export const datasets = [synthetic];
