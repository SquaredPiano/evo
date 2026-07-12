import type { Metadata } from "next";
import { Instrument_Sans, JetBrains_Mono, Instrument_Serif } from "next/font/google";
import { Toaster } from "sonner";
import { cn } from "@/lib/utils";
import ErrorBoundary from "@/components/ui/ErrorBoundary";
import "./globals.css";

const instrumentSans = Instrument_Sans({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "optional",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  display: "optional",
});

const instrumentSerif = Instrument_Serif({
  subsets: ["latin"],
  variable: "--font-display",
  weight: "400",
  style: ["normal", "italic"],
  display: "optional",
});

export const metadata: Metadata = {
  title: { default: "Proteus", template: "%s - Proteus" },
  description:
    "The genomic design IDE. Generate, score, and edit DNA sequences with the Evo 2 foundation model and live ESMFold structure prediction.",
  icons: { icon: "/favicon.svg" },
  metadataBase: new URL("https://evo.bio"),
  openGraph: {
    title: "Proteus - Genomic Design IDE",
    description: "Co-design genomes with an IDE that thinks out loud. Powered by the Evo 2 model and ESMFold.",
    type: "website",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={cn(instrumentSans.variable, jetbrainsMono.variable, instrumentSerif.variable)} suppressHydrationWarning>
      <body className="antialiased min-h-screen font-sans" style={{ background: "var(--cream)", color: "var(--ink)" }}>
        <a href="#main-content" className="skip-to-content">Skip to content</a>
        <ErrorBoundary>{children}</ErrorBoundary>
        <Toaster
          position="top-right"
          toastOptions={{
            style: {
              background: "var(--surface-raised)",
              color: "var(--text-primary)",
              border: "1px solid var(--ghost-border)",
              borderRadius: "12px",
              fontFamily: "var(--font-sans)",
            },
          }}
        />
      </body>
    </html>
  );
}
