/**
 * Fictional source documents for the synthetic patient.
 * Each paragraph is a list of segments; segments with an `id` are citable passages.
 */
const s = (id, text) => ({ id, text });

export const documents = [
  {
    id: 'DOC-ANE-2022-0614',
    type: 'Anesthesia record',
    category: 'Assessments',
    title: 'Anesthesia record — knee arthroscopy (left)',
    date: '2022-06-14',
    time: '08:40',
    author: 'Dr. P. Ostrowski',
    department: 'Department of Anesthesiology',
    facility: 'St. Aurel Hospital',
    sections: [
      {
        heading: 'Procedure',
        paragraphs: [
          ['Elective arthroscopic partial meniscectomy, left knee. ASA physical status II.'],
        ],
      },
      {
        heading: 'Anesthetic technique',
        paragraphs: [
          [
            'General anesthesia with propofol induction and sevoflurane maintenance. ',
            s('ane-airway', 'Airway: laryngeal mask airway size 4, inserted at first attempt; Mallampati class II.'),
          ],
          ['Intraoperative course uneventful. Estimated blood loss minimal.'],
        ],
      },
      {
        heading: 'Recovery room',
        paragraphs: [
          [
            s('ane-ponv', 'Postoperative nausea and vomiting (PONV) in the recovery room, two episodes, treated with ondansetron 4 mg IV.'),
            ' Symptoms resolved after 40 minutes. Discharged from recovery after 2 h 15 min.',
          ],
        ],
      },
      {
        heading: 'Recommendation',
        paragraphs: [
          [s('ane-recommend', 'Document PONV history; consider multimodal PONV prophylaxis for future anesthetics.')],
        ],
      },
    ],
  },
  {
    id: 'DOC-ALG-2024-0308',
    type: 'Allergy registry',
    category: 'Lists',
    title: 'Allergy and intolerance registry entry',
    date: '2024-03-08',
    time: '10:12',
    author: 'Dr. E. Lindqvist',
    department: 'General practice',
    facility: 'Lindqvist & Partners Practice',
    sections: [
      {
        heading: 'Recorded entry',
        paragraphs: [
          ['Substance class: beta-lactam antibiotic.'],
          [s('alg-penicillin', 'Penicillin — rash.')],
          [s('alg-detail', 'Generalized maculopapular rash on day 3 of amoxicillin therapy (2009); no angioedema, no respiratory involvement.')],
          ['Verification: patient-reported, confirmed against 2009 practice notes. Status: active.'],
        ],
      },
      {
        heading: 'Other substances',
        paragraphs: [['No other drug, food, latex or contrast-media reactions recorded.']],
      },
    ],
  },
  {
    id: 'DOC-CAR-2025-0211',
    type: 'Cardiology letter',
    category: 'Letters',
    title: 'Outpatient cardiology letter',
    date: '2025-02-11',
    author: 'Dr. H. Nakamura',
    department: 'Cardiology outpatient clinic',
    facility: 'St. Aurel Hospital',
    sections: [
      {
        heading: 'Diagnosis',
        paragraphs: [
          [s('car-af', 'Paroxysmal atrial fibrillation, first documented on Holter ECG, January 2025.')],
        ],
      },
      {
        heading: 'Findings',
        paragraphs: [
          [s('car-echo', 'Transthoracic echocardiography: LVEF 58 %, no relevant valvular disease, left atrium mildly dilated.')],
          ['CHA2DS2-VASc score 3 (female sex, hypertension, diabetes).'],
        ],
      },
      {
        heading: 'Plan',
        paragraphs: [
          [
            s('car-apixaban-start', 'Start apixaban 5 mg twice daily.'),
            ' Metoprolol succinate 47.5 mg once daily for rate control. Cardiology review in 12 months.',
          ],
        ],
      },
    ],
  },
  {
    id: 'DOC-RES-2026-0903',
    type: 'Respiratory consultation',
    category: 'Consultations',
    title: 'Sleep medicine follow-up',
    date: '2026-09-03',
    time: '14:30',
    author: 'Dr. S. Brandt',
    department: 'Pulmonology and sleep medicine',
    facility: 'St. Aurel Hospital',
    sections: [
      {
        heading: 'Indication',
        paragraphs: [['Annual follow-up of obstructive sleep apnea.']],
      },
      {
        heading: 'History',
        paragraphs: [
          [s('res-osa', 'Obstructive sleep apnea, moderate; polysomnography 2023 with AHI 28/h.')],
        ],
      },
      {
        heading: 'Current treatment',
        paragraphs: [
          [
            s('res-cpap', 'CPAP nightly at 9 cmH2O; good adherence reported (device data: mean use 6.8 h/night).'),
            ' Residual AHI on device 3.1/h. Epworth Sleepiness Scale 6/24.',
          ],
        ],
      },
      {
        heading: 'Assessment',
        paragraphs: [
          ['Well controlled on CPAP. Mask fit satisfactory. '],
          [s('res-bring', 'Patient should bring the CPAP device for any planned hospital admission.')],
        ],
      },
    ],
  },
  {
    id: 'DOC-DIS-2026-0921',
    type: 'Discharge summary',
    category: 'Letters',
    title: 'Discharge summary — internal medicine',
    date: '2026-09-21',
    author: 'Dr. A. Ferreira',
    department: 'Internal medicine, ward 3B',
    facility: 'St. Aurel Hospital',
    sections: [
      {
        heading: 'Admission',
        paragraphs: [['Admitted 18 Sep 2026 via the emergency department. Discharged 21 Sep 2026.']],
      },
      {
        heading: 'Reason for admission',
        paragraphs: [['Melena for two days; hemoglobin 9.8 g/dL on admission.']],
      },
      {
        heading: 'Course',
        paragraphs: [
          [
            s('dis-ulcer', 'Gastroscopy 19 Sep 2026: duodenal ulcer (Forrest IIc), no active bleeding.'),
            ' Treated with intravenous pantoprazole, later oral. Helicobacter pylori negative. No transfusion required. Hemoglobin stable at 10.6 g/dL on discharge.',
          ],
        ],
      },
      {
        heading: 'Diagnoses',
        paragraphs: [
          ['1. Upper gastrointestinal bleeding from duodenal ulcer.'],
          ['2. Paroxysmal atrial fibrillation, currently sinus rhythm.'],
          ['3. Type 2 diabetes mellitus. 4. Arterial hypertension. 5. Obstructive sleep apnea on CPAP.'],
        ],
      },
      {
        heading: 'Medication on discharge',
        paragraphs: [
          [s('dis-apixaban', 'Apixaban discontinued.'), ' Restart to be decided by the treating cardiologist after gastroenterology review.'],
          ['Pantoprazole 40 mg twice daily for 8 weeks. Metoprolol succinate 47.5 mg once daily. Metformin 1000 mg twice daily. Ramipril 5 mg once daily.'],
        ],
      },
      {
        heading: 'Follow-up',
        paragraphs: [['Gastroenterology review in 6–8 weeks. Cardiology review regarding anticoagulation.']],
      },
    ],
  },
  {
    id: 'DOC-SUR-2026-1005',
    type: 'Surgical referral',
    category: 'Letters',
    title: 'Referral for elective surgery',
    date: '2026-10-05',
    author: 'Dr. L. Moreau',
    department: 'General and visceral surgery',
    facility: 'St. Aurel Hospital',
    sections: [
      {
        heading: 'Findings',
        paragraphs: [['Recurrent biliary colic since spring 2026. Ultrasound: multiple gallstones, gallbladder wall not thickened.']],
      },
      {
        heading: 'Plan',
        paragraphs: [
          [s('sur-plan', 'Elective laparoscopic cholecystectomy planned for 02 Nov 2026 for symptomatic cholelithiasis.')],
          ['Pre-anesthesia assessment requested.'],
        ],
      },
    ],
  },
  {
    id: 'DOC-MED-2026-1012',
    type: 'Medication reconciliation',
    category: 'Lists',
    title: 'Current medication list',
    date: '2026-10-12',
    time: '09:05',
    author: 'Dr. E. Lindqvist',
    department: 'General practice',
    facility: 'Lindqvist & Partners Practice',
    sections: [
      {
        heading: 'Active medication',
        paragraphs: [
          [s('med-apixaban', 'Apixaban 5 mg twice daily — active.')],
          ['Metoprolol succinate 47.5 mg once daily — active.'],
          [s('med-metformin', 'Metformin 1000 mg twice daily — active.')],
          ['Ramipril 5 mg once daily — active.'],
          ['Pantoprazole 40 mg once daily — active.'],
        ],
      },
      {
        heading: 'Note',
        paragraphs: [['List compiled from practice prescribing records. Hospital discharge letter of September 2026 not yet received at time of compilation.']],
      },
    ],
  },
  {
    id: 'DOC-PRE-2026-1012',
    type: 'Pre-operative assessment',
    category: 'Assessments',
    title: 'Pre-operative assessment questionnaire',
    date: '2026-10-12',
    time: '11:20',
    author: 'Nurse T. Okafor',
    department: 'Pre-anesthesia clinic',
    facility: 'St. Aurel Hospital',
    sections: [
      {
        heading: 'Planned procedure',
        paragraphs: [['Laparoscopic cholecystectomy, 02 Nov 2026.']],
      },
      {
        heading: 'Questionnaire (patient self-report, nurse-assisted)',
        paragraphs: [
          [s('pre-allergy', 'Allergies: No known drug allergies.')],
          [s('pre-anesthesia', 'Previous anesthesia: No problems with previous anesthesia.')],
          [s('pre-osa', 'Sleep apnea / CPAP: None reported.')],
          ['Dentures or loose teeth: none. Exercise tolerance: two flights of stairs without stopping.'],
        ],
      },
      {
        heading: 'Measurements',
        paragraphs: [[s('pre-bmi', 'Height 168 cm, weight 91 kg, BMI 32.2 kg/m².'), ' Blood pressure 138/82 mmHg, heart rate 68/min, regular.']],
      },
    ],
  },
  {
    id: 'DOC-LAB-2026-1027',
    type: 'Laboratory report',
    category: 'Diagnostics',
    title: 'Pre-operative laboratory panel',
    date: '2026-10-27',
    time: '07:55',
    author: 'Central laboratory',
    department: 'Laboratory medicine',
    facility: 'St. Aurel Hospital',
    sections: [
      {
        heading: 'Hematology',
        paragraphs: [
          [s('lab-hb', 'Hemoglobin 11.2 g/dL (reference 12.0–15.5).')],
          ['Platelets 245 × 10⁹/L (reference 150–400).'],
        ],
      },
      {
        heading: 'Clinical chemistry',
        paragraphs: [
          [s('lab-renal', 'Creatinine 1.12 mg/dL; eGFR 52 mL/min/1.73 m² (reference > 60).')],
          ['Potassium 4.4 mmol/L. Sodium 139 mmol/L.'],
          [s('lab-hba1c', 'HbA1c 7.1 %.')],
        ],
      },
      {
        heading: 'Coagulation',
        paragraphs: [[s('lab-coag', 'INR 1.0. aPTT 29 s.')]],
      },
    ],
  },
  {
    id: 'DOC-GPL-2026-1012',
    type: 'Problem list',
    category: 'Lists',
    title: 'Problem list and past medical history',
    date: '2026-10-12',
    author: 'Dr. E. Lindqvist',
    department: 'General practice',
    facility: 'Lindqvist & Partners Practice',
    sections: [
      {
        heading: 'Active problems',
        paragraphs: [
          [s('gpl-dm', 'Type 2 diabetes mellitus, since 2014; oral therapy.')],
          ['Arterial hypertension, since 2012.'],
          ['Paroxysmal atrial fibrillation, since 2025.'],
          ['Obstructive sleep apnea, since 2023.'],
          ['Symptomatic cholelithiasis, 2026.'],
        ],
      },
      {
        heading: 'Past medical history',
        paragraphs: [
          [s('gpl-knee', 'Arthroscopic partial meniscectomy, left knee — 2022.')],
          [s('gpl-mammo', 'Screening mammography, BI-RADS 1 — 2025.')],
          [s('gpl-colon', 'Colonoscopy, two tubular adenomas removed — 2020.')],
          [s('gpl-cataract', 'Cataract surgery, right eye — 2019.')],
          [s('gpl-zoster', 'Herpes zoster, thoracic dermatome T6 — 2018; resolved.')],
          [s('gpl-disc', 'Lumbar disc protrusion L4/5, conservative treatment — 2017; resolved.')],
          [s('gpl-plantar', 'Plantar fasciitis, right — 2016; resolved.')],
          [s('gpl-iron', 'Iron-deficiency anemia, oral iron — 2015; resolved.')],
          [s('gpl-hallux', 'Hallux valgus correction, left foot — 2013.')],
          [s('gpl-append', 'Appendectomy — 1984.')],
          [s('gpl-tonsil', 'Tonsillectomy — 1970.')],
        ],
      },
    ],
  },
  {
    id: 'DOC-ORT-2021-1104',
    type: 'Orthopedic clinic letter',
    category: 'Letters',
    title: 'Fracture clinic — final review',
    date: '2021-11-04',
    author: 'Dr. M. Varga',
    department: 'Orthopedics and trauma surgery',
    facility: 'St. Aurel Hospital',
    sections: [
      {
        heading: 'Diagnosis',
        paragraphs: [['Distal radius fracture, left, after a fall on ice, 23 Sep 2021. Treated conservatively with a forearm cast for 6 weeks.']],
      },
      {
        heading: 'Findings at final review',
        paragraphs: [[s('ort-healed', 'Fracture healed in good position; full range of motion restored.'), ' No further follow-up required.']],
      },
    ],
  },
];
