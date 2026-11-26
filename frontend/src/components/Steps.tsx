const LABELS = ["Bilgiler", "Önizleme", "Kayıt"] as const;

export function Steps({ current }: { current: 1 | 2 | 3 }) {
  return (
    <ol className="ft-steps" aria-label="Adımlar">
      {LABELS.map((label, index) => {
        const step = index + 1;
        return (
          <li
            key={label}
            aria-current={step === current ? "step" : undefined}
            data-done={step < current || undefined}
          >
            {label}
          </li>
        );
      })}
    </ol>
  );
}
