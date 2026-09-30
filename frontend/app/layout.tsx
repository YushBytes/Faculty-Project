import type { Metadata } from "next";
import { Suspense } from "react";
import "./globals.css";
import { SessionProvider } from "@/lib/auth/session";

export const metadata: Metadata = {
  title: "ACADLYTICS — Academic Performance Intelligence",
  description: "Academic performance intelligence for SRM Institute of Science and Technology: reliable ingestion, deterministic analytics, attention, interventions and reports across the academic hierarchy.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Suspense>
          <SessionProvider>{children}</SessionProvider>
        </Suspense>
      </body>
    </html>
  );
}
