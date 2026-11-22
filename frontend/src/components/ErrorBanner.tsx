import { Notice } from "./ui";

interface ErrorBannerProps {
  message: string;
}

/** Error text from the API, shown as-is so the user sees the real reason. */
export function ErrorBanner({ message }: ErrorBannerProps) {
  return (
    <Notice variant="error" role="alert">
      {message}
    </Notice>
  );
}
