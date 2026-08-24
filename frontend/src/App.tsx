import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "@/lib/auth";
import { ThemeProvider } from "@/hooks/use-theme";
import { ProtectedRoute } from "@/components/ProtectedRoute";
import { AppLayout } from "@/components/AppLayout";
import { LoginPage } from "@/pages/LoginPage";
import { CallsPage } from "@/pages/CallsPage";
import { CallDetailPage } from "@/pages/CallDetailPage";
import { AdminPBXPage } from "@/pages/AdminPBXPage";
import { AdminUsersPage } from "@/pages/AdminUsersPage";

const queryClient = new QueryClient();

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <AuthProvider>
          <BrowserRouter>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route element={<ProtectedRoute />}>
                <Route element={<AppLayout />}>
                  <Route index element={<Navigate to="/calls" replace />} />
                  <Route path="/calls" element={<CallsPage />} />
                  <Route path="/calls/:id" element={<CallDetailPage />} />
                </Route>
              </Route>
              <Route element={<ProtectedRoute roles={["SUPERADMIN"]} />}>
                <Route element={<AppLayout />}>
                  <Route path="/admin/pbx" element={<AdminPBXPage />} />
                  <Route path="/admin/users" element={<AdminUsersPage />} />
                </Route>
              </Route>
              <Route path="*" element={<Navigate to="/calls" replace />} />
            </Routes>
          </BrowserRouter>
        </AuthProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}
