import type { Bundle, Doc, L } from './types'

// Invented demo patient. None of this comes from the challenge dataset.
const l = (en: string, de: string): L => ({ en, de })

const documents: Doc[] = [
  {
    id: '90010003',
    title: l('Discharge letter, internal medicine', 'Entlassungsbrief, Innere Medizin'),
    short: l('Letter 11/2023', 'Brief 11/2023'),
    date: '2023-11-20',
    kind: l('Discharge letter', 'Entlassungsbrief'),
    department: l('Internal medicine', 'Innere Medizin'),
    paragraphs: [
      {
        id: 'dx',
        text: l(
          'Diagnoses: paroxysmal atrial fibrillation (CHA2DS2-VASc 4), type 2 diabetes, chronic kidney disease stage G3a, arterial hypertension, osteoarthritis of the right knee.',
          'Diagnosen: Paroxysmales Vorhofflimmern (CHA2DS2-VASc 4), Diabetes mellitus Typ 2, chronische Niereninsuffizienz G3a, arterielle Hypertonie, Gonarthrose rechts.',
        ),
      },
      {
        id: 'allergy',
        text: l(
          'Allergies: **penicillin** (generalised rash in 2009).',
          'Allergien: **Penicillin** (generalisiertes Exanthem 2009).',
        ),
      },
      {
        id: 'echo',
        text: l(
          'Echocardiography: preserved left-ventricular function (**EF 55%**), left atrium mildly dilated, no relevant valve disease.',
          'Echokardiographie: Erhaltene LV-Funktion (**EF 55%**), linker Vorhof leicht dilatiert, keine relevanten Vitien.',
        ),
      },
      {
        id: 'meds',
        text: l(
          'Discharge medication: **Eliquis 5 mg 1-0-1**, Metformin 500 mg 1-0-1, Ramipril 5 mg 1-0-0, Bisoprolol 2.5 mg 1-0-0, Atorvastatin 20 mg 0-0-1.',
          'Entlassungsmedikation: **Eliquis 5mg 1-0-1**, Metformin 500mg 1-0-1, Ramipril 5mg 1-0-0, Bisoprolol 2,5mg 1-0-0, Atorvastatin 20mg 0-0-1.',
        ),
      },
      {
        id: 'vitals',
        text: l(
          'Height 164 cm, weight **82 kg**, BMI 30.5. Blood pressure 138/82 mmHg.',
          'Größe 164 cm, Gewicht **82 kg**, BMI 30,5. RR 138/82 mmHg.',
        ),
      },
      {
        id: 'plan',
        text: l(
          'Recommended: kidney function check in 3 months, HbA1c check at the GP, knee replacement on the **right** after cardiology clearance.',
          'Empfohlen: Kontrolle der Nierenfunktion in 3 Monaten, HbA1c-Kontrolle beim Hausarzt, Knie-TEP **rechts** nach kardiologischer Freigabe.',
        ),
      },
    ],
  },
  {
    id: '90010005',
    title: l('Laboratory report', 'Laborbefund'),
    short: l('Lab 11/2023', 'Labor 11/2023'),
    date: '2023-11-18',
    kind: l('Laboratory', 'Labor'),
    department: l('Central laboratory', 'Zentrallabor'),
    paragraphs: [
      {
        id: 'kidney',
        text: l(
          'Creatinine 1.2 mg/dl, **eGFR 52 ml/min/1.73 m²**, potassium 4.6 mmol/l.',
          'Kreatinin 1,2 mg/dl, **eGFR 52 ml/min/1,73 m²**, Kalium 4,6 mmol/l.',
        ),
      },
      {
        id: 'other',
        text: l(
          'HbA1c 7.1%, haemoglobin 12.9 g/dl, platelets 241 G/l, INR 1.1.',
          'HbA1c 7,1%, Hämoglobin 12,9 g/dl, Thrombozyten 241 G/l, INR 1,1.',
        ),
      },
    ],
  },
  {
    id: '90010004',
    title: l('Long-term ECG', 'Langzeit-EKG'),
    short: l('Long-term ECG 11/2023', 'Langzeit-EKG 11/2023'),
    date: '2023-11-17',
    kind: l('Other finding', 'Sonstiger Befund'),
    department: l('Cardiology', 'Kardiologie'),
    paragraphs: [
      {
        id: 'ecg',
        text: l(
          'Recording over 23 h. **Two episodes of atrial fibrillation** (longest 3 h 10 min), otherwise sinus rhythm, mean heart rate 72/min, no pauses.',
          'Aufzeichnung über 23 Stunden. **Zwei Episoden von Vorhofflimmern** (längste 3 h 10 min), sonst Sinusrhythmus, mittlere HF 72/min, keine Pausen.',
        ),
      },
    ],
  },
  {
    id: '90010007',
    title: l('Outpatient letter, orthopaedics', 'Ambulanzbrief, Orthopädie'),
    short: l('Orthopaedics 02/2024', 'Orthopädie 02/2024'),
    date: '2024-02-12',
    kind: l('Outpatient letter', 'Ambulanzbrief'),
    department: l('Orthopaedics', 'Orthopädie'),
    paragraphs: [
      {
        id: 'findings',
        text: l(
          'Advanced osteoarthritis of the **left** knee, pain on walking after 200 m. Allergies: none known.',
          'Fortgeschrittene Gonarthrose **links**, Gehstrecke schmerzbedingt 200 m. Allergien: keine bekannt.',
        ),
      },
      {
        id: 'vitals',
        text: l(
          'Height 164 cm, weight 79 kg, **BMI 25**.',
          'Größe 164 cm, Gewicht 79 kg, **BMI 25**.',
        ),
      },
      {
        id: 'plan',
        text: l(
          'Knee replacement planned for **18.03.2024**. Anticoagulation to be paused as agreed with cardiology.',
          'Knie-TEP geplant am **18.03.2024**. Pausieren der Antikoagulation nach Rücksprache mit der Kardiologie.',
        ),
      },
    ],
  },
]

export const bundle: Bundle = {
  patient: {
    name: 'Eva Probst',
    sex: l('female', 'weiblich'),
    born: '1957-09-02',
    age: 66,
    heightCm: 164,
    weightKg: 79,
    bmi: 29.4,
    weightSource: { doc: '90010007', para: 'vitals' },
    bmiConflict: 'bmi',
  },
  labels: [
    { id: 'antithrombotic', title: l('Blood thinners', 'Blutverdünner') },
    { id: 'allergy', title: l('Allergies', 'Allergien') },
    { id: 'heart', title: l('Heart function', 'Herzfunktion') },
    { id: 'other', title: l('Also relevant', 'Weiteres') },
  ],
  groups: [
    {
      label: 'antithrombotic',
      title: l('Blood thinners', 'Blutverdünner'),
      facts: [
        {
          id: 'apixaban',
          value: l('Eliquis 5 mg, 1-0-1', 'Eliquis 5 mg, 1-0-1'),
          detail: l('apixaban, twice daily; pause before surgery', 'Apixaban, zweimal täglich; vor der Operation pausieren'),
          sources: [
            { doc: '90010003', para: 'meds' },
            { doc: '90010007', para: 'plan' },
          ],
        },
      ],
    },
    {
      label: 'allergy',
      title: l('Allergies', 'Allergien'),
      facts: [
        {
          id: 'penicillin',
          value: l('Penicillin allergy', 'Penicillinallergie'),
          detail: l('generalised rash', 'generalisiertes Exanthem'),
          sources: [{ doc: '90010003', para: 'allergy' }],
          conflicts: ['allergy'],
        },
      ],
    },
    {
      label: 'heart',
      title: l('Heart function', 'Herzfunktion'),
      facts: [
        {
          id: 'ef',
          value: l('Ejection fraction 55%', 'Ejektionsfraktion 55%'),
          detail: l('preserved function, echo November 2023', 'erhaltene Funktion, Echo November 2023'),
          sources: [{ doc: '90010003', para: 'echo' }],
        },
        {
          id: 'af',
          value: l('Paroxysmal atrial fibrillation', 'Paroxysmales Vorhofflimmern'),
          detail: l('two episodes on long-term ECG', 'zwei Episoden im Langzeit-EKG'),
          sources: [{ doc: '90010004', para: 'ecg' }],
        },
      ],
    },
    {
      label: 'other',
      title: l('Also relevant', 'Weiteres'),
      facts: [
        {
          id: 'egfr',
          value: l('eGFR 52 ml/min', 'eGFR 52 ml/min'),
          detail: l('kidney disease stage G3a', 'Niereninsuffizienz G3a'),
          sources: [{ doc: '90010005', para: 'kidney' }],
        },
        {
          id: 'metformin',
          value: l('Metformin 500 mg, 1-0-1', 'Metformin 500 mg, 1-0-1'),
          detail: l('type 2 diabetes, HbA1c 7.1%', 'Diabetes mellitus Typ 2, HbA1c 7,1%'),
          sources: [
            { doc: '90010003', para: 'meds' },
            { doc: '90010005', para: 'other' },
          ],
        },
        {
          id: 'knee',
          value: l('Knee replacement on 18.03.2024', 'Knie-TEP am 18.03.2024'),
          detail: l('side documented differently', 'Seite uneinheitlich dokumentiert'),
          sources: [{ doc: '90010007', para: 'plan' }],
          conflicts: ['side'],
        },
      ],
    },
  ],
  notDocumented: [
    { id: 'anaesthesia', title: l('Previous anaesthesia', 'Frühere Narkosen') },
    { id: 'airway', title: l('Airway assessment', 'Atemwegsbeurteilung') },
  ],
  conflicts: [
    {
      id: 'side',
      title: l('Side of the knee operation', 'Seite der Knieoperation'),
      summary: l('right in the discharge letter, left in the orthopaedic letter', 'rechts im Entlassungsbrief, links im Orthopädiebrief'),
      sources: [
        { doc: '90010003', para: 'plan' },
        { doc: '90010007', para: 'findings' },
      ],
    },
    {
      id: 'allergy',
      title: l('Penicillin allergy against "none known"', 'Penicillinallergie gegen „keine bekannt"'),
      summary: l('allergy documented in 11/2023, denied in 02/2024', 'Allergie 11/2023 dokumentiert, 02/2024 verneint'),
      sources: [
        { doc: '90010003', para: 'allergy' },
        { doc: '90010007', para: 'findings' },
      ],
    },
    {
      id: 'bmi',
      title: l('BMI does not match height and weight', 'BMI passt nicht zu Größe und Gewicht'),
      summary: l('stated 25, but 79 kg at 164 cm gives 29.4', 'angegeben 25, aber 79 kg bei 164 cm ergibt 29,4'),
      sources: [{ doc: '90010007', para: 'vitals' }],
    },
  ],
  documents,
  records: [
    { doc: '90010003', relevance: 95, labels: { antithrombotic: 1, allergy: 1, heart: 1, other: 2 }, excerpt: 'meds', conflicts: ['side', 'allergy'] },
    { doc: '90010007', relevance: 90, labels: { antithrombotic: 1, other: 1 }, excerpt: 'plan', conflicts: ['side', 'allergy', 'bmi'] },
    { doc: '90010005', relevance: 58, labels: { other: 2 }, excerpt: 'kidney', conflicts: [] },
    { doc: '90010004', relevance: 41, labels: { heart: 1 }, excerpt: 'ecg', conflicts: [] },
  ],
}

export const defaultSituation = {
  patientName: 'Eva Probst',
  birthNumber: '570902/4711',
  departments: ['anaesthesiology'],
  prompt: 'Anaesthetist, pre-operative check before knee replacement',
}

export const departmentOptions: { id: string; name: L }[] = [
  { id: 'anaesthesiology', name: l('Anaesthesiology', 'Anästhesiologie') },
  { id: 'surgery', name: l('Surgery', 'Chirurgie') },
  { id: 'internal', name: l('Internal medicine', 'Innere Medizin') },
  { id: 'cardiology', name: l('Cardiology', 'Kardiologie') },
  { id: 'oncology', name: l('Oncology', 'Onkologie') },
  { id: 'emergency', name: l('Emergency medicine', 'Notfallmedizin') },
  { id: 'gp', name: l('General practice', 'Allgemeinmedizin') },
  { id: 'radiology', name: l('Radiology', 'Radiologie') },
  { id: 'ophthalmology', name: l('Ophthalmology', 'Augenheilkunde') },
]
