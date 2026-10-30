"""Clinical categories are independent of the frontend's ten renderer types."""

CATEGORIES = [
    ("demographics", "Patient details", "Date of birth, sex and other explicitly recorded identity attributes", "patient sidebar"),
    ("encounters", "Encounters", "Admission/discharge events, departments and reasons for encounters", "timeline / findings"),
    ("diagnoses", "Diagnoses", "Confirmed, suspected and negated conditions with status", "conditions"),
    ("symptoms", "Symptoms and episodes", "Symptoms, onset, course and explicitly documented causal attribution", "findings"),
    ("allergies", "Allergies and reactions", "Substances, recorded reactions and explicit negative allergy statements", "alerts / conditions"),
    ("medications", "Medications", "Drug, strength, administered dose, route, schedule and prescription context", "medication"),
    ("vitals", "Vitals and anthropometrics", "Weight, height, blood pressure components, pulse and temperature", "measurement / trend"),
    ("laboratory", "Laboratory findings", "Numerical tests and qualitative laboratory findings", "measurement / findings"),
    ("imaging", "Imaging findings", "Findings, anatomical site and laterality; examination itself is a procedure", "findings"),
    ("functional_tests", "Functional assessments", "Ejection fraction, rhythm, cognitive or other functional assessments", "measurement / findings"),
    ("pathology", "Pathology and tumour characteristics", "Histology, staging, grade, receptors and proliferation markers", "oncology"),
    ("procedures", "Procedures and investigations", "Performed or explicitly not-performed investigations/interventions; negation does not establish completion. Recommended/planned interventions belong to care_plans", "procedures"),
    ("care_plans", "Care plans", "Recommended or scheduled interventions, timing and responsible service", "plan"),
    ("followups", "Follow-up recommendations", "Recommended reviews/checks and separately evidenced completion events", "followups"),
    ("medical_history", "Medical and surgical history", "Explicit historical context and prior operations", "conditions / procedures"),
    ("family_history", "Family history", "Conditions and negative history concerning relatives, not the patient", "conditions / findings"),
    ("social_history", "Social history and support", "Documented living situation, support, smoking and alcohol history", "findings"),
    ("other_clinical", "Other clinical information", "Supported clinical information not yet covered; retain specific concept and wording", "findings"),
]
