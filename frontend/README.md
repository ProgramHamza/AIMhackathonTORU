# Clinical Workspace (prototype)

Frontend-only design prototype of a clinical documentation interface. Not clinically validated, not for clinical use.

- Mock patient search (any input, or empty fields, opens the default patient; nothing is downloaded)
- Patient panel: identity, context, full patient record, contradictions, timeline
- Important information for the current task, with key terms linked to the exact source passage
- Right-side pop-up for sources, contradictions and the full patient record (closes on outside click or Esc)

Includes a **fictional** patient (`src/data/`). If `src/data/real/` and `../data` are present, the TRACK-1 hackathon patient is shown too.

```bash
npm install
npm run dev      # http://localhost:5173
npm run build    # static build in dist/
```

Requires Node.js 18+.
