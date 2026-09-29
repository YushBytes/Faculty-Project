import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/lib/auth/session";

export const metadata: Metadata = {
  title: "ACADLYTICS — Academic Performance Intelligence",
  description: "A clear, faculty-led workspace for assessment outcomes and student support.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className="h-full antialiased"
    >
      <body className="min-h-full flex flex-col"><AuthProvider>{children}</AuthProvider></body>
    </html>
  );
}
