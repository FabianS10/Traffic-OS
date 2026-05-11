import { useState } from "react";
import { useAuth } from "../context/AuthContext"

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID || "";
const GITHUB_CLIENT_ID = import.meta.env.VITE_GITHUB_CLIENT_ID || "";

export default function AuthPage() {
  const { login, API } = useAuth();
  const [mode, setMode]   = useState("login");   // "login" | "register"
  const [email, setEmail] = useState("");
  const [pass,  setPass]  = useState("");
  const [user,  setUser]  = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setError(""); setLoading(true);
    try {
      const endpoint = mode === "login" ? "/auth/login" : "/auth/register";
      const body = mode === "login"
        ? { email, password: pass }
        : { email, password: pass, username: user };

      const r = await fetch(`${API}${endpoint}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || "Authentication failed");
      login(data.user, data.access_token, data.refresh_token);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  const oauthRedirect = (provider) => {
    const params = {
      google: `https://accounts.google.com/o/oauth2/v2/auth?client_id=${GOOGLE_CLIENT_ID}&redirect_uri=${encodeURIComponent(window.location.origin+"/auth/callback")}&response_type=code&scope=openid%20email%20profile&state=google`,
      github: `https://github.com/login/oauth/authorize?client_id=${GITHUB_CLIENT_ID}&redirect_uri=${encodeURIComponent(window.location.origin+"/auth/callback")}&scope=read:user%20user:email&state=github`,
    };
    window.location.href = params[provider];
  };

  return (
    <div style={styles.wrap}>
      <div style={styles.grid} aria-hidden="true" />
      <div style={styles.panel}>

        {/* Logotype */}
        <div style={styles.logo}>
          <svg width="32" height="32" viewBox="0 0 32 32" fill="none">
            <circle cx="16" cy="16" r="14" stroke="#4ECDC4" strokeWidth="1.5"/>
            <path d="M8 16 Q16 6 24 16 Q16 26 8 16Z" fill="#4ECDC4" opacity="0.15" stroke="#4ECDC4" strokeWidth="1"/>
            <circle cx="16" cy="16" r="3" fill="#4ECDC4"/>
            <path d="M16 8 L16 13M16 19 L16 24M8 16 L13 16M19 16 L24 16" stroke="#4ECDC4" strokeWidth="1.5" strokeLinecap="round"/>
          </svg>
          <span style={styles.logoText}>TRAFFICOS</span>
        </div>
        <p style={styles.sub}>Urban Intelligence Platform · Fusagasugá</p>

        {/* Mode toggle */}
        <div style={styles.toggle}>
          {["login","register"].map(m => (
            <button key={m} onClick={() => { setMode(m); setError(""); }}
              style={{ ...styles.toggleBtn, ...(mode===m ? styles.toggleActive : {}) }}>
              {m === "login" ? "SIGN IN" : "REGISTER"}
            </button>
          ))}
        </div>

        <form onSubmit={submit} style={styles.form}>
          {mode === "register" && (
            <div style={styles.field}>
              <label style={styles.label}>USERNAME</label>
              <input style={styles.input} value={user} onChange={e=>setUser(e.target.value)}
                placeholder="callsign" autoComplete="username" required />
            </div>
          )}
          <div style={styles.field}>
            <label style={styles.label}>EMAIL</label>
            <input style={styles.input} type="email" value={email} onChange={e=>setEmail(e.target.value)}
              placeholder="operator@fasc.co" autoComplete="email" required />
          </div>
          <div style={styles.field}>
            <label style={styles.label}>PASSWORD</label>
            <input style={styles.input} type="password" value={pass} onChange={e=>setPass(e.target.value)}
              placeholder="••••••••••••" autoComplete="current-password" required />
          </div>

          {error && <p style={styles.error}>{error}</p>}

          <button type="submit" style={{ ...styles.btn, opacity: loading ? 0.6 : 1 }} disabled={loading}>
            {loading ? "AUTHENTICATING..." : mode === "login" ? "ENTER SYSTEM" : "CREATE ACCOUNT"}
          </button>
        </form>

        <div style={styles.divider}><span style={styles.dividerText}>OR CONTINUE WITH</span></div>

        <div style={styles.oauthRow}>
          <button style={styles.oauthBtn} onClick={() => oauthRedirect("google")}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
              <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
              <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
              <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05"/>
              <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
            </svg>
            Google
          </button>
          <button style={styles.oauthBtn} onClick={() => oauthRedirect("github")}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12z"/>
            </svg>
            GitHub
          </button>
        </div>

        <p style={styles.footer}>
          F.A.S.C. Machine Learning Solutions S.A.S. · Fusagasugá, Colombia
        </p>
      </div>
    </div>
  );
}

const styles = {
  wrap: {
    minHeight: "100vh",
    background: "#080E1A",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    position: "relative",
    overflow: "hidden",
    fontFamily: "'Space Mono', monospace",
  },
  grid: {
    position: "absolute", inset: 0,
    backgroundImage: `linear-gradient(rgba(78,205,196,0.04) 1px, transparent 1px), linear-gradient(90deg, rgba(78,205,196,0.04) 1px, transparent 1px)`,
    backgroundSize: "40px 40px",
  },
  panel: {
    background: "rgba(12,20,36,0.95)",
    border: "1px solid rgba(78,205,196,0.2)",
    borderRadius: 4,
    padding: "40px 36px",
    width: "100%",
    maxWidth: 420,
    position: "relative",
    zIndex: 1,
    boxShadow: "0 0 60px rgba(78,205,196,0.05), inset 0 0 40px rgba(78,205,196,0.02)",
  },
  logo: { display:"flex", alignItems:"center", gap:12, marginBottom:6 },
  logoText: { fontSize:20, fontWeight:700, color:"#4ECDC4", letterSpacing:"0.15em" },
  sub: { fontSize:11, color:"rgba(78,205,196,0.5)", marginBottom:28, letterSpacing:"0.08em" },
  toggle: { display:"flex", background:"rgba(78,205,196,0.06)", borderRadius:3, padding:3, marginBottom:24, border:"1px solid rgba(78,205,196,0.12)" },
  toggleBtn: { flex:1, padding:"8px 0", fontSize:11, letterSpacing:"0.1em", background:"transparent", border:"none", cursor:"pointer", color:"rgba(78,205,196,0.45)", transition:"all 0.2s" },
  toggleActive: { background:"rgba(78,205,196,0.15)", color:"#4ECDC4", borderRadius:2 },
  form: { display:"flex", flexDirection:"column", gap:16 },
  field: { display:"flex", flexDirection:"column", gap:6 },
  label: { fontSize:10, letterSpacing:"0.12em", color:"rgba(78,205,196,0.5)" },
  input: {
    background: "rgba(78,205,196,0.04)",
    border: "1px solid rgba(78,205,196,0.2)",
    borderRadius: 3,
    padding: "10px 14px",
    color: "#E8F4F4",
    fontSize: 13,
    fontFamily: "'Space Mono', monospace",
    outline: "none",
    transition: "border-color 0.2s",
  },
  error: { fontSize:12, color:"#FF6B6B", letterSpacing:"0.04em", margin:0 },
  btn: {
    padding: "12px 0",
    background: "rgba(78,205,196,0.12)",
    border: "1px solid rgba(78,205,196,0.4)",
    borderRadius: 3,
    color: "#4ECDC4",
    fontSize: 12,
    letterSpacing: "0.15em",
    cursor: "pointer",
    fontFamily: "'Space Mono', monospace",
    fontWeight: 700,
    transition: "all 0.2s",
    marginTop: 4,
  },
  divider: { display:"flex", alignItems:"center", gap:12, margin:"24px 0 20px" },
  dividerText: { fontSize:10, color:"rgba(78,205,196,0.3)", letterSpacing:"0.1em", whiteSpace:"nowrap" },
  oauthRow: { display:"grid", gridTemplateColumns:"1fr 1fr", gap:10 },
  oauthBtn: {
    display: "flex", alignItems: "center", justifyContent: "center", gap: 8,
    padding: "10px 0",
    background: "rgba(78,205,196,0.04)",
    border: "1px solid rgba(78,205,196,0.15)",
    borderRadius: 3,
    color: "rgba(78,205,196,0.7)",
    fontSize: 12,
    letterSpacing: "0.06em",
    cursor: "pointer",
    fontFamily: "'Space Mono', monospace",
    transition: "all 0.2s",
  },
  footer: { marginTop:28, fontSize:10, color:"rgba(78,205,196,0.25)", textAlign:"center", letterSpacing:"0.04em" },
};
