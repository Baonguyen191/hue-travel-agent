interface ComingSoonPageProps {
  title: string;
}

/** Temporary placeholder for routes whose screens are built in later steps. */
export function ComingSoonPage({ title }: ComingSoonPageProps) {
  return (
    <section className="rounded-lg border border-dashed border-slate-300 bg-white p-6">
      <h1 className="text-xl font-semibold">{title}</h1>
      <p className="mt-2 text-sm text-slate-600">Màn hình này đang được xây dựng.</p>
    </section>
  );
}
