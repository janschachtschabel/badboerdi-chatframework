import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'BadBoerdi Studio',
  description: 'Konfigurationsoberfläche für den BadBoerdi Chatbot',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="de">
      <body>{children}</body>
    </html>
  );
}
