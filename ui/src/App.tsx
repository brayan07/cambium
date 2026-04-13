import { BrowserRouter, Routes, Route, Navigate } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Layout } from "./components/Layout";
import { ChatPage } from "./pages/ChatPage";
import { InboxPage } from "./pages/InboxPage";
import { PlaceholderPage } from "./pages/PlaceholderPage";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: true,
    },
  },
});

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<Navigate to="/chat" replace />} />
            <Route path="/chat" element={<ChatPage />} />
            <Route path="/inbox" element={<InboxPage />} />
            <Route
              path="/work"
              element={
                <PlaceholderPage
                  title="Work Items"
                  description="Task hierarchy — Phase 4"
                />
              }
            />
            <Route
              path="/dashboard"
              element={
                <PlaceholderPage
                  title="Dashboard"
                  description="System overview — Phase 4"
                />
              }
            />
            <Route
              path="/mind/*"
              element={
                <PlaceholderPage
                  title="Mind"
                  description="Constitution, preferences, knowledge — Phase 5"
                />
              }
            />
            <Route
              path="/config"
              element={
                <PlaceholderPage
                  title="Configuration"
                  description="Routines, adapters, timers — Phase 5"
                />
              }
            />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
