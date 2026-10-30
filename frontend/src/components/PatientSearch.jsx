import { useEffect, useRef, useState } from 'react';
import { assess, importPatient } from '../lib/backend';
import { detectLang, makeT, useLang } from '../lib/i18n';

/**
 * Patient search. No patient ships with the app: the doctor imports a patient folder, then types
 * the role and task. The backend (POST /api/assess) checks name + date of birth and assesses the task.
 */

const CHARACTERS = [
  { id: 'purple', color: '#6b2bff', left: 62, width: 104, height: 232, radius: '0', face: { top: 26, left: 34 }, eyes: 'dot', gap: 20 },
  { id: 'black', color: '#22252a', left: 150, width: 62, height: 164, radius: '0', face: { top: 22, left: 12 }, eyes: 'ball', gap: 22 },
  { id: 'orange', color: '#ff7a21', left: 0, width: 178, height: 92, radius: '89px 89px 0 0', face: { top: 34, left: 62 }, eyes: 'dot', gap: 30 },
  { id: 'yellow', color: '#e9d21d', left: 196, width: 80, height: 122, radius: '40px 40px 0 0', face: { top: 34, left: 18 }, eyes: 'dot', gap: 20 },
];

const MOUTHS = {
  line: <path d="M3 6H21" />,
  short: <path d="M8 6H16" />,
  smile: <path d="M4 3Q12 12 20 3" />,
  frown: <path d="M4 10Q12 2 20 10" />,
  o: <ellipse cx="12" cy="6" rx="3.6" ry="4" />,
};

const EXPRESSIONS = {
  idle: { purple: 'short', black: null, orange: 'smile', yellow: 'line' },
  name: { purple: 'smile', black: null, orange: 'o', yellow: 'smile' },
  birthday: { purple: 'o', black: null, orange: 'smile', yellow: 'line' },
  task: { purple: 'smile', black: null, orange: 'smile', yellow: 'o' },
  searching: { purple: 'o', black: null, orange: 'o', yellow: 'o' },
  error: { purple: 'frown', black: null, orange: 'frown', yellow: 'frown' },
  success: { purple: 'smile', black: null, orange: 'smile', yellow: 'smile' },
};

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

function Character({ c, mouth, refFn }) {
  return (
    <div
      ref={refFn}
      className="login-char"
      style={{ left: c.left, width: c.width, height: c.height, background: c.color, borderRadius: c.radius }}
    >
      <div className="login-face" style={{ top: c.face.top, left: c.face.left }}>
        <div className="login-eyes" style={{ gap: c.gap - (c.eyes === 'ball' ? 12 : 7) }}>
          {[0, 1].map((i) =>
            c.eyes === 'ball' ? (
              <span key={i} className="login-eye login-eye--ball">
                <span className="login-pupil" />
              </span>
            ) : (
              <span key={i} className="login-eye login-eye--dot" />
            ),
          )}
        </div>
        {mouth && (
          <svg className="login-mouth" viewBox="0 0 24 12" aria-hidden="true">
            {MOUTHS[mouth]}
          </svg>
        )}
      </div>
    </div>
  );
}

function CrossLogo() {
  return (
    <svg width="32" height="32" viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="12" fill="#182027" />
      <path d="M9.4 4h5.2v5.4H20v5.2h-5.4V20H9.4v-5.4H4V9.4h5.4z" fill="#fff" />
    </svg>
  );
}

export function PatientSearch({ onFound }) {
  const { lang, setLang, t } = useLang();
  const [name, setName] = useState('');
  const [birth, setBirth] = useState('');
  const [taskText, setTaskText] = useState('');
  const [focus, setFocus] = useState(null);
  const [error, setError] = useState(null);
  const [step, setStep] = useState(null);
  const [success, setSuccess] = useState(false);
  const [importing, setImporting] = useState(false);
  const [importNote, setImportNote] = useState(null);

  const charEls = useRef({});
  const nameRef = useRef(null);
  const birthRef = useRef(null);
  const taskRef = useRef(null);
  const buttonRef = useRef(null);
  const sceneRef = useRef(null);
  const mouse = useRef(null);
  const timers = useRef([]);
  const folderInput = useRef(null);
  const filesInput = useRef(null);

  useEffect(() => {
    const field = taskRef.current;
    if (!field) return;
    const fitContent = () => {
      field.style.height = 'auto';
      const style = window.getComputedStyle(field);
      const borders = parseFloat(style.borderTopWidth) + parseFloat(style.borderBottomWidth);
      field.style.height = `${field.scrollHeight + borders}px`;
    };
    fitContent();
    window.addEventListener('resize', fitContent);
    return () => window.removeEventListener('resize', fitContent);
  }, [taskText]);

  let mode = 'idle';
  if (success) mode = 'success';
  else if (step) mode = 'searching';
  else if (error) mode = 'error';
  else if (focus === 'name') mode = 'name';
  else if (focus === 'birth') mode = 'birthday';
  else if (focus === 'task') mode = 'task';

  const modeRef = useRef(mode);
  modeRef.current = mode;

  useEffect(() => {
    const update = () => {
      const m = modeRef.current;
      for (const c of CHARACTERS) {
        const el = charEls.current[c.id];
        if (!el) continue;
        const r = el.getBoundingClientRect();
        const cx = r.left + r.width / 2;
        const cy = r.top + c.face.top;
        let t = mouse.current;
        const dx = t ? t.x - cx : 0;
        const dy = t ? t.y - cy : 0;
        let skew = clamp(-dx / 45, -9, 9);
        let stretch = 1;
        if (m !== 'idle' && m !== 'error' && m !== 'success') stretch = c.id === 'orange' ? 1 : 1.05;
        if (m === 'error') skew = c.id === 'purple' ? 10 : 4;
        if (m === 'success') skew = 0;
        const reach = c.eyes === 'ball' ? 7 : 11;
        el.style.setProperty('--skew', `${skew}deg`);
        el.style.setProperty('--stretch', stretch);
        el.style.setProperty('--fx', `${clamp(dx / 18, -reach, reach)}px`);
        el.style.setProperty('--fy', `${clamp(dy / 26, -reach * 0.7, reach * 0.7)}px`);
        el.style.setProperty('--px', `${clamp(dx / 40, -3, 3)}px`);
        el.style.setProperty('--py', `${clamp(dy / 50, -3, 3)}px`);
      }
    };
    let frame = 0;
    const schedule = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(update);
    };
    const onMove = (e) => {
      mouse.current = { x: e.clientX, y: e.clientY };
      schedule();
    };
    window.addEventListener('pointermove', onMove);
    window.addEventListener('resize', schedule);
    schedule();
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('resize', schedule);
    };
  }, [mode]);

  useEffect(() => {
    const list = [];
    const blink = (id) => {
      list.push(
        setTimeout(() => {
          const el = charEls.current[id];
          if (el) {
            el.dataset.blink = 'true';
            list.push(setTimeout(() => delete el.dataset.blink, 140));
          }
          blink(id);
        }, 2500 + Math.random() * 3500),
      );
    };
    CHARACTERS.forEach((c) => blink(c.id));
    const pending = timers.current;
    return () => {
      list.forEach(clearTimeout);
      pending.forEach(clearTimeout);
    };
  }, []);

  const later = (ms, fn) => timers.current.push(setTimeout(fn, ms));

  const finish = (dataset, task) => {
    setSuccess(true);
    later(450, () => onFound(dataset, task));
  };

  const submit = async (e) => {
    e.preventDefault();
    if (step || success) return;
    setError(null);
    // The typed task sets the UI language; unclear text keeps the current one.
    const next = detectLang(taskText) ?? lang;
    if (next !== lang) setLang(next);
    const task = taskText.trim();
    if (!task) {
      setError(makeT(next)('enterTask'));
      return;
    }
    setStep('searching');
    try {
      const dataset = await assess({ name: name.trim(), birthDate: birth, task, lang: next });
      setStep(null);
      finish(dataset, dataset.tasks[0]);
    } catch (err) {
      setStep(null);
      setError(err.message);
    }
  };

  const upload = async (e) => {
    const list = e.target.files;
    if (!list?.length || importing) return;
    setError(null);
    setImportNote(null);
    setImporting(true);
    try {
      const r = await importPatient(list, lang);
      setName(r.patient.name);
      setBirth(r.patient.birthDate);
      const warn = r.warnings?.length ? ` · ${t('importWarnings', { n: r.warnings.length })}` : '';
      setImportNote({ text: t('imported', { name: r.patient.name, docs: r.documents, facts: r.facts }) + warn, warnings: r.warnings ?? [] });
      taskRef.current?.focus();
    } catch (err) {
      setError(err.message);
    } finally {
      setImporting(false);
      e.target.value = '';
    }
  };

  const edit = (setter) => (e) => {
    setter(e.target.value);
    setError(null);
  };

  const expr = EXPRESSIONS[mode];

  const field = (label, input) => (
    <label className={`login-field ${error ? 'is-error' : ''}`}>
      <span>{label}</span>
      {input}
    </label>
  );

  return (
    <div className="login">
      <div ref={sceneRef} className="login-scene" data-mode={mode} aria-hidden="true">
        {CHARACTERS.map((c) => (
          <Character key={c.id} c={c} mouth={expr[c.id]} refFn={(el) => (charEls.current[c.id] = el)} />
        ))}
      </div>

      <form className="login-form" onSubmit={submit} noValidate>
        <div className="login-head">
          <CrossLogo />
          <h1 className="panel-title m-0">{t('findPatientTitle')}</h1>
        </div>

        {field(
          t('patientName'),
          <input
            ref={nameRef}
            type="text"
            autoComplete="off"
            value={name}
            onChange={edit(setName)}
            onFocus={() => setFocus('name')}
            onBlur={() => setFocus(null)}
          />,
        )}
        {field(
          t('birthDate'),
          <input
            ref={birthRef}
            type="date"
            value={birth}
            onChange={edit(setBirth)}
            onFocus={() => setFocus('birth')}
            onBlur={() => setFocus(null)}
          />,
        )}
        {field(
          t('roleTask'),
          <textarea
            ref={taskRef}
            rows={4}
            autoComplete="off"
            value={taskText}
            onChange={edit(setTaskText)}
            onFocus={() => setFocus('task')}
            onBlur={() => setFocus(null)}
          />,
        )}
        <p className="login-error" role="alert">
          {error ?? ''}
        </p>

        <button ref={buttonRef} type="submit" className="login-btn" disabled={Boolean(step) || success}>
          {step ? (
            <>
              <span className="login-spinner" aria-hidden="true" />
              {t(step)}
            </>
          ) : success ? (
            t('loaded')
          ) : (
            t('findPatient')
          )}
        </button>

        <div className="login-import">
          <button type="button" disabled={importing || Boolean(step)} onClick={() => folderInput.current?.click()}>
            {t('importFolder')}
          </button>
          <button type="button" disabled={importing || Boolean(step)} onClick={() => filesInput.current?.click()}>
            {t('importFiles')}
          </button>
          <input ref={folderInput} type="file" hidden webkitdirectory="" onChange={upload} />
          <input ref={filesInput} type="file" hidden multiple accept=".json,application/json" onChange={upload} />
        </div>
        <p className="login-import-note" role="status" title={importNote?.warnings.join(' · ') || undefined}>
          {importing ? (
            <>
              <span className="login-spinner login-spinner--dark" aria-hidden="true" />
              {t('importing')}
            </>
          ) : (
            importNote?.text ?? t('importHint')
          )}
        </p>
      </form>
    </div>
  );
}
