/** Marks transport, hotel and booking data that comes from mock providers. */
export function MockBadge({ className = "" }: { className?: string }) {
  return (
    <span className={`rounded bg-muc px-1.5 py-0.5 text-[11px] font-semibold tracking-wider text-on-son ${className}`.trim()}>
      MÔ PHỎNG
    </span>
  );
}
