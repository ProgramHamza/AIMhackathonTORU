import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { SourceContext } from "./lib/SourceContext";
import { refKey } from "./lib/sources";
import { AppHeader } from "./components/AppHeader";
import { PatientPanel } from "./components/PatientPanel";
import { ImportantPanel } from "./components/ImportantPanel";
import { DetailPanel } from "./components/DetailPanel";
import { PatientSearch } from "./components/PatientSearch";
import { MedicalExams } from "./components/MedicalExams";
import { LangContext, makeT } from "./lib/i18n";
import { assess } from "./lib/backend";


export default function App() {
  // The assessment on screen: a backend response (lib/backend.js). Nothing is bundled.
  const [active, setActive] = useState(null);
  const dataset = active?.dataset;
  const task = active?.task;
  const { patient, encounter } = dataset ?? {};
  const [detail, setDetail] = useState(null);
  const [open, setOpen] = useState(false);
  const [recordFilter, setRecordFilter] = useState("all");
  const found = active !== null;

  // UI language: set from the typed task's language, switchable in the header. A backend
  // assessment is requested again in the new language so its labels and explanations follow.
  const [lang, setLangState] = useState("en");
  const [busy, setBusy] = useState(false);
  const langRequest = useRef(0);

  const state = useRef({ detail, open, active });
  state.current = { detail, open, active };
  const returnFocus = useRef(null);

  const setLang = useCallback((next) => {
    setLangState(next);
    const current = state.current.active?.dataset;
    if (!current?.query || current.lang === next) {
      langRequest.current += 1;
      setBusy(false);
      return;
    }
    const id = ++langRequest.current;
    setBusy(true);
    assess({ ...current.query, lang: next })
      .then((ds) => {
        if (id !== langRequest.current) return;
        const { detail: cur } = state.current;
        if (cur?.kind === "contradiction" && !ds.encounter.contradictions.some((c) => c.id === cur.id)) setOpen(false);
        setActive({ dataset: ds, task: ds.tasks[0] });
      })
      .catch(() => {})
      .finally(() => {
        if (id === langRequest.current) setBusy(false);
      });
  }, []);

  const langApi = useMemo(() => ({ lang, t: makeT(lang), setLang, busy }), [lang, setLang, busy]);
  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  const show = useCallback((next) => {
    if (!state.current.open) returnFocus.current = document.activeElement;
    setDetail(next);
    setOpen(true);
  }, []);

  const openSource = useCallback(
    (source, citedFor) => {
      const { detail: cur, open: isOpen } = state.current;
      const from =
        isOpen && (cur?.kind === "contradiction" || cur?.kind === "record")
          ? cur
          : null;
      show({ kind: "source", citation: { ...source, citedFor }, from });
    },
    [show],
  );

  const focusContradiction = useCallback(
    (id) => show({ kind: "contradiction", id }),
    [show],
  );
  const openRecord = useCallback(() => show({ kind: "record" }), [show]);

  const close = useCallback((restoreFocus) => {
    setOpen(false);
    const el = returnFocus.current;
    returnFocus.current = null;
    if (restoreFocus && el instanceof HTMLElement && el.isConnected)
      requestAnimationFrame(() => el.focus({ preventScroll: true }));
  }, []);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => {
      if (e.key === "Escape") close(true);
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, [open, close]);

  const sourceApi = useMemo(
    () => ({
      store: dataset?.store,
      openSource,
      focusContradiction,
      activeKey:
        open && detail?.kind === "source" ? refKey(detail.citation) : null,
      activeContradiction:
        open && detail?.kind === "contradiction" ? detail.id : null,
      openRecord,
      recordOpen: open && detail?.kind === "record",
    }),
    [dataset?.store, openSource, focusContradiction, openRecord, detail, open],
  );

  if (!found)
    return (
      <LangContext.Provider value={langApi}>
      <div className="flex h-full flex-col">
        <AppHeader clinician={{ name: langApi.t("clinician") }} />
        <PatientSearch
          onFound={(next, picked) => {
            setDetail(null);
            setOpen(false);
            setRecordFilter("all");
            setActive({ dataset: next, task: picked });
          }}
        />
      </div>
      </LangContext.Provider>
    );

  return (
    <LangContext.Provider value={langApi}>
    <SourceContext.Provider value={sourceApi}>
      <div className="flex h-full flex-col">
        <div className="flex h-full min-h-0 flex-col" inert={open ? '' : undefined}>
        <AppHeader
          clinician={encounter.clinician}
          task={task}
          onNewSearch={() => {
            langRequest.current += 1;
            setBusy(false);
            setOpen(false);
            setDetail(null);
            setActive(null);
          }}
        />
        <main className="workspace" data-exams-open="true">
          <PatientPanel
            key={`patient-${dataset.key}`}
            patient={patient}
            encounter={encounter}
          />
          <ImportantPanel
            key={`important-${dataset.key}-${task.id}`}
            encounter={encounter}
            task={task}
          />
          <MedicalExams
            key={`exams-${dataset.key}`}
            documents={dataset.documents}
            encounter={encounter}
            task={task}


          />
        </main>
        </div>
        <DetailPanel
          detail={detail}
          open={open}
          contradictions={[...encounter.contradictions, ...(encounter.reviewFindings ?? [])]}
          record={encounter.record}
          onBack={show}
          onClose={() => close(true)}
          recordFilter={recordFilter}
          onRecordFilter={setRecordFilter}
        />
      </div>
    </SourceContext.Provider>
    </LangContext.Provider>
  );
}

