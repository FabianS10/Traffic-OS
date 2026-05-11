import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { AuthProvider, useAuth } from "./context/AuthContext";
import AuthPage from "./pages/AuthPage";
import Dashboard from "./pages/Dashboard";
import OAuthCallback from "./pages/OAuthCallback";

function AppRoutes() {
  const { token, ready, demoMode } = useAuth();

  if (!ready) return (
    <div style={styles.loading}>
      <div style={styles.loadingInner}>
        <div style={styles.pulse} />
        TRAFFICOS INITIALISING...
      </div>
    </div>
  );

  return (
    <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <Routes>
        {/* Demo mode: skip auth entirely */}
        {demoMode ? (
          <Route path="/*" element={<Dashboard />} />
        ) : (
          <>
            <Route path="/auth"          element={!token ? <AuthPage />      : <Navigate to="/" />} />
            <Route path="/auth/callback" element={<OAuthCallback />} />
            <Route path="/*"             element={token  ? <Dashboard />     : <Navigate to="/auth" />} />
          </>
        )}
      </Routes>
    </BrowserRouter>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <AppRoutes />
    </AuthProvider>
  );
}

const styles = {
  loading: {
    display: "flex", alignItems: "center", justifyContent: "center",
    height: "100vh", background: "#080E1A",
  },
  loadingInner: {
    display: "flex", alignItems: "center", gap: 12,
    color: "#4ECDC4", fontFamily: "'Space Mono', monospace", fontSize: 13, letterSpacing: "0.15em"
  },
  pulse: {
    width: 8, height: 8, borderRadius: "50%", background: "#4ECDC4",
    animation: "pulse 1.2s ease-in-out infinite",
    boxShadow: "0 0 12px #4ECDC4"
  },
};
