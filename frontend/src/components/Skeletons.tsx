interface SkeletonListProps {
  count: number;
  label: string;
}

/** Placeholder cards shown while a list loads. */
export function CardSkeletons({ count, label }: SkeletonListProps) {
  return (
    <div role="status" aria-label={label} className="grid gap-3 sm:grid-cols-2">
      {Array.from({ length: count }, (_, index) => (
        <div key={index} className="h-40 animate-pulse rounded-lg border border-slate-200 bg-slate-100" />
      ))}
    </div>
  );
}
