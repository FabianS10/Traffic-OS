import { createContext, useContext, useState, useEffect } from "react";

export const AuthCtx = createContext(null);
export const useAuth = () => useContext(AuthCtx);

const DEMO_MODE = import.meta.env.VITE_DEMO_MODE === "true";

export const AuthProvider = ({ children }) => {
  const API = import.meta.env.VITE_API_URL || "http://localhost:8000/api";

  const [user,  setUser]  = useState(null);
  const [token, setToken] = useState(() => localStorage.getItem("token"));
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (DEMO_MODE) {
      // Bypass all auth — auto-login as demo user
      fetch(`${API}/auth/demo-token`)
        .then(r => r.ok ? r.json() : null)
        .then(data => {
          if (data) {
            setUser(data.user);
            setToken(data.access_token);
            localStorage.setItem("token", data.access_token);
          }
          setReady(true);
        })
        .catch(() => {
          // Even if backend is down, let the app load
          setUser({ username: "DEMO", id: 1 });
          setToken("demo-bypass-token-trafficos");
          setReady(true);
        });
      return;
    }

    if (!token) { setReady(true); return; }

    fetch(`${API}/auth/me`, { headers: { Authorization: `Bearer ${token}` } })
      .then(r => r.ok ? r.json() : null)
      .then(u => { setUser(u); setReady(true); })
      .catch(() => { localStorage.removeItem("token"); setReady(true); });
  }, [token, API]);

  const login = (userData, accessToken, refreshToken) => {
    setUser(userData);
    setToken(accessToken);
    localStorage.setItem("token", accessToken);
    if (refreshToken) localStorage.setItem("refresh", refreshToken);
  };

  const logout = () => {
    if (DEMO_MODE) return; // No logout in demo mode
    setUser(null);
    setToken(null);
    localStorage.removeItem("token");
    localStorage.removeItem("refresh");
    window.location.href = "/auth";
  };

  return (
    <AuthCtx.Provider value={{ user, token, login, logout, API, ready, demoMode: DEMO_MODE }}>
      {children}
    </AuthCtx.Provider>
  );
};
