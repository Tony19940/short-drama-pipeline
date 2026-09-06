export function Guide({ now }: { what?: string; now: string; next?: string }) {
  return (
    <p className="step-now">
      <span>这一步</span>
      {now}
    </p>
  );
}
