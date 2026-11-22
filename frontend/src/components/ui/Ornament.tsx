export function Ornament({ className = "" }: { className?: string }) {
  return <div aria-hidden="true" className={`ornament-band ${className}`.trim()} />;
}
