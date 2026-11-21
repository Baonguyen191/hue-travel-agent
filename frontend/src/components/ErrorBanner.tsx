interface ErrorBannerProps {
  message: string;
}

/** Error text from the API, shown as-is so the user sees the real reason. */
export function ErrorBanner({ message }: ErrorBannerProps) {
  return (
    <div role="alert" className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-800">
      {message}
    </div>
  );
}
