"use client";

// QueryClientProvider holds state and React context, so it must be a Client
// Component. Everything rendered inside it can still be a Server Component;
// the boundary only decides where *this* file's code runs.

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";

export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(() => new QueryClient());
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}
