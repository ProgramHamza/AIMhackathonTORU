export function PanelHeader({ id, title, aside, kicker, children }) {
  return (
    <header className="sticky top-0 z-10 bg-panel px-6 pt-5 pb-3">
      {kicker}
      <div className="flex items-baseline justify-between gap-4 border-b-2 border-ink pb-2">
        <h2 id={id} className="panel-title m-0">
          {title}
        </h2>
        {aside}
      </div>
      {children}
    </header>
  );
}
