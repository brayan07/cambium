import { BrowserRouter, Routes, Route, Navigate } from "react-router";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Layout } from "./components/Layout";
import { ChatPage } from "./pages/ChatPage";
import { InboxPage } from "./pages/InboxPage";
import { WorkPage } from "./pages/WorkPage";
import { DashboardPage } from "./pages/DashboardPage";
import { MemoryPage } from "./pages/MemoryPage";
import { ConfigPage } from "./pages/ConfigPage";

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
            <Route path="/work" element={<WorkPage />} />
            <Route path="/dashboard" element={<DashboardPage />} />
            <Route path="/memory" element={<MemoryPage />} />
            <Route path="/config" element={<ConfigPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
