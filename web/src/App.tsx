import { useEffect, useState } from "react";
import { api, type LLMSettings } from "./api";
import { APP_KANJI, APP_NAME, Icon } from "./ui";
import Library from "./pages/Library";
import Meeting from "./pages/Meeting";
import Record from "./pages/Record";
import Settings from "./pages/Settings";

// Hash routes: #/ library · #/r/<id> recording · #/settings
const useRoute = () => {
  const [hash, setHash] = useState(location.hash.slice(1) || "/");
  useEffect(() => {
    const on = () => setHash(location.hash.slice(1) || "/");
    addEventListener("hashchange", on);
    return () => removeEventListener("hashchange", on);
  }, []);
  return hash;
};

export default function App() {
  const route = useRoute();
  const [llm, setLlm] = useState<LLMSettings | null>(null);
  const refreshLlm = () => api.llm().then(setLlm).catch(() => {});
  useEffect(() => { refreshLlm(); }, []);

  const rid = route.match(/^\/r\/([\w-]+)/)?.[1];
  const prov = llm?.provider ? llm.providers[llm.provider] : null;
  const section = route.startsWith("/settings") ? "settings" : route.startsWith("/record") ? "record" : "library";

  return (
    <div className="shell">
      <aside className="side tone">
        <a className="brand" href="#/"><span className="seal">{APP_KANJI}</span>{APP_NAME}</a>
        <nav className="nav">
          <a href="#/record" aria-current={section === "record" ? "page" : undefined}><Icon name="mic" />Record<small>録音</small></a>
          <a href="#/" aria-current={section === "library" ? "page" : undefined}><Icon name="book" />Library<small>記録</small></a>
          <a href="#/settings" aria-current={section === "settings" ? "page" : undefined}><Icon name="gear" />Settings<small>設定</small></a>
        </nav>
        <div className="foot">
          <b><span className="dot" />Audio stays on this Mac</b>
          {prov ? (
            <div style={{ marginTop: 6, display: "flex", gap: 6, alignItems: "center" }}>
              <span className={`dot ${prov.local ? "" : "cloud"}`} />
              AI: {prov.label}{prov.local ? "" : " (cloud)"}
            </div>
          ) : <div style={{ marginTop: 6 }}>AI notes: <a href="#/settings">connect a model</a></div>}
        </div>
      </aside>
      <main className="main">
        {section === "settings" ? <Settings onSaved={setLlm} />
          : section === "record" ? <Record />
          : rid ? <Meeting key={rid} id={rid} llm={llm} />
          : <Library />}
      </main>
    </div>
  );
}
