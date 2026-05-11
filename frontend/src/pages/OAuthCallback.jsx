import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

export default function OAuthCallback() {
  const { login, API } = useAuth();
  const navigate       = useNavigate();

  useEffect(() => {
    const params   = new URLSearchParams(window.location.search);
    const code     = params.get("code");
    const provider = params.get("state");  // "google" | "github"

    if (!code || !provider) { navigate("/auth"); return; }

    fetch(`${API}/auth/oauth/callback`, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify({ code, provider }),
    })
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(data => { login(data.user, data.access_token, data.refresh_token); navigate("/"); })
      .catch(() => navigate("/auth"));
  }, []);

  return (
    <div style={{ display:"flex", alignItems:"center", justifyContent:"center", height:"100vh", background:"#080E1A", color:"#4ECDC4", fontFamily:"'Space Mono', monospace", fontSize:13, letterSpacing:"0.1em" }}>
      AUTHENTICATING VIA OAUTH...
    </div>
  );
}
