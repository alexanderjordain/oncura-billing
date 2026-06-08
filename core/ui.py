"""Visual identity — matched to UI_STYLE_GUIDE.md (oncura-programs).

Same theme + patterns as the FLEX app + oncura-apps portal. Includes:
- header / inject for theme
- record_button (light-green commit-to-ledger button)
- initials_input (bordered sign-off card)
- persistence_warning (GitHub-token absent banner shown BEFORE record button)
- scroll_top_on_step_change (wizard step transitions)
"""
from __future__ import annotations

import streamlit as st

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,500;9..144,600;9..144,700&family=Hanken+Grotesk:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap');

:root {
  --canvas:#F0F2F4; --surface:#FFFFFF; --ink:#2A3742; --blue:#3A6A9A;
  --blue-deep:#2F567E; --green:#469B68; --amber:#E3A033; --muted:#6B7785; --line:#E2E6EA;
  --serif:'Fraunces',Georgia,serif; --sans:'Hanken Grotesk',-apple-system,sans-serif;
  --mono:'IBM Plex Mono',ui-monospace,monospace;
}

.stApp {
  background:
    radial-gradient(900px 520px at 90% -10%, rgba(58,106,154,.06), transparent 60%),
    radial-gradient(720px 480px at -6% 6%, rgba(70,155,104,.05), transparent 55%),
    var(--canvas);
}
html, body, [class*="css"], .stApp, p, li, label, .stMarkdown { font-family: var(--sans); color: var(--ink); }
h1, h2, h3, h4 { font-family: var(--serif) !important; color: var(--blue) !important; letter-spacing:-.01em; font-weight:600; }

.oncura-head { margin:.2rem 0 1.4rem 0; padding:.1rem 0 1rem 1rem; border-bottom:1px solid var(--line); border-left:4px solid var(--green); }
.oncura-head .kicker { font-family:var(--mono); text-transform:uppercase; letter-spacing:.28em; font-size:.7rem; color:var(--amber); margin-bottom:.5rem; }
.oncura-head h1 { font-size:2.4rem; line-height:1.05; margin:0; color:var(--blue) !important; }
.oncura-head .sub { font-family:var(--sans); color:var(--muted); font-size:1rem; margin:.5rem 0 0 0; max-width:62ch; }

[data-testid="stMetric"] {
  background:var(--surface); border:1px solid var(--line);
  border-left:3px solid var(--blue); border-radius:6px;
  padding:.85rem 1rem; box-shadow:0 1px 3px rgba(42,55,66,.05);
}
[data-testid="stMetricLabel"] p {
  font-family:var(--mono) !important; text-transform:uppercase;
  letter-spacing:.12em; font-size:.66rem !important; color:var(--muted) !important;
}
[data-testid="stMetricValue"] {
  font-family:var(--mono) !important; font-weight:600;
  font-variant-numeric:tabular-nums; color:var(--blue) !important; letter-spacing:-.01em;
}

.stButton > button, .stDownloadButton > button, .stLinkButton > a, .stLinkButton > a:visited {
  background:#FFFFFF !important; color:#1F3D5C !important; border:1.5px solid #1F3D5C !important;
  font-family:var(--sans) !important; font-weight:700 !important; border-radius:6px;
  text-decoration:none !important; transition:transform .08s ease, box-shadow .15s ease, background .15s ease;
}
.stButton > button:hover, .stDownloadButton > button:hover, .stLinkButton > a:hover {
  background:#EAF2FA !important; border-color:#1F3D5C !important; color:#1F3D5C !important;
  transform:translateY(-1px); box-shadow:0 4px 14px rgba(31,61,92,.18);
}
.stButton > button:disabled, .stDownloadButton > button:disabled {
  background:#F3F4F6 !important; border-color:#D1D5DB !important; color:#9CA3AF !important; cursor:not-allowed;
}

section[data-testid="stSidebar"] { background:var(--surface); border-right:1px solid var(--line); }
[data-testid="stHeader"] { background: var(--surface) !important; border-bottom:1px solid var(--line); }
[data-testid="stDataFrame"] { font-variant-numeric:tabular-nums; }
[data-testid="stDecoration"] { display:none; }
footer { visibility:hidden; }

/* Mark / Record buttons — light green tint to signal commit-to-ledger */
.element-container:has(.oncura-record-btn-anchor) + .element-container button[kind] {
  background: #DFF5E1 !important; color: #1B6E3A !important; border: 1px solid #82C18C !important;
}
.element-container:has(.oncura-record-btn-anchor) + .element-container button[kind]:hover:not(:disabled) {
  background: #C6EFCE !important; border-color: #1B6E3A !important;
}
.element-container:has(.oncura-record-btn-anchor) + .element-container button[kind]:disabled {
  background: #F2F8F3 !important; color: #82C18C !important; border-color: #C6E8C9 !important; opacity: 0.7;
}
.oncura-record-btn-anchor { display: none; }
</style>
"""


def inject():
    st.markdown(_CSS, unsafe_allow_html=True)


def header(title: str, subtitle: str = "", kicker: str = "ONCURA · BILLING"):
    sub = f'<p class="sub">{subtitle}</p>' if subtitle else ""
    st.markdown(
        f'<div class="oncura-head"><div class="kicker">{kicker}</div>'
        f"<h1>{title}</h1>{sub}</div>",
        unsafe_allow_html=True,
    )


def persistence_warning() -> None:
    """Warn ABOVE a record button if no GitHub token is configured."""
    from . import store

    if store._github_token():
        return
    st.warning(
        ":material/warning: **No `GITHUB_TOKEN` configured** — the charge log and CIM map "
        "will save to the local filesystem only. On Streamlit Cloud this means closing the "
        "browser tab loses the audit trail, and a re-run could double-charge a customer. "
        "Add `GITHUB_TOKEN` in App → Settings → Secrets before committing this cycle.",
        icon=":material/warning:",
    )


def record_button(label: str, *, key: str, disabled: bool = False,
                  use_container_width: bool = False, help: str | None = None) -> bool:
    """Light-green tinted commit button (CSS-targeted via the sentinel below)."""
    st.markdown('<div class="oncura-record-btn-anchor"></div>',
                unsafe_allow_html=True)
    return st.button(
        label, key=key, disabled=disabled,
        use_container_width=use_container_width, help=help,
    )


def initials_input(audit_key: str, *, disabled: bool = False) -> str:
    """Bordered sign-off card with initials text input. Persists in SS['user_initials']."""
    live_val = (
        st.session_state.get(audit_key)
        or st.session_state.get("user_initials", "")
        or ""
    ).strip().upper()

    with st.container(border=True):
        if live_val:
            st.markdown(
                f"##### :green[:material/check_circle:&nbsp; Initials captured: {live_val}]"
            )
            st.caption(
                "The **record button** below is now enabled. Initials persist for "
                "the session so subsequent cycles auto-fill."
            )
        else:
            st.markdown(
                "##### :red[:material/priority_high:&nbsp; INITIALS REQUIRED]"
            )
            st.caption(
                "Enter your initials below to enable the **record button** — "
                "like initialing a paper sign-off sheet."
            )
        val = st.text_input(
            "Your initials (for the audit log)",
            value=st.session_state.get("user_initials", ""),
            max_chars=4,
            key=audit_key,
            placeholder="e.g. AJ",
            disabled=disabled,
            label_visibility="collapsed",
        )
    cleaned = (val or "").strip().upper()
    if cleaned:
        st.session_state["user_initials"] = cleaned
    return cleaned


def scroll_top_on_step_change(wizard_key: str, current_step) -> None:
    """Scroll the page to the top whenever a wizard step changes."""
    import streamlit.components.v1 as components

    prev_key = f"__scroll_prev_{wizard_key}"
    prev = st.session_state.get(prev_key)
    st.session_state[prev_key] = current_step
    if prev is None or prev == current_step:
        return
    components.html(
        """
        <script>
        (function() {
            const w = (window.parent && window.parent !== window) ? window.parent : window.top;
            if (!w) return;
            try { if (w.history && 'scrollRestoration' in w.history)
                w.history.scrollRestoration = 'manual'; } catch (e) {}
            const SEL = ['section[data-testid="stMain"]', 'div[data-testid="stAppViewContainer"]',
                         'div[data-testid="stAppViewBlockContainer"]', 'section.main', 'main'];
            const scroll = () => {
                try {
                    w.scrollTo({top:0, left:0, behavior:'auto'});
                    const doc = w.document;
                    if (doc?.documentElement) doc.documentElement.scrollTop = 0;
                    if (doc?.body) doc.body.scrollTop = 0;
                    for (const s of SEL) {
                        const el = doc.querySelector(s);
                        if (el) { if (typeof el.scrollTo === 'function') el.scrollTo({top:0, behavior:'auto'}); el.scrollTop = 0; }
                    }
                } catch (e) {}
            };
            scroll(); setTimeout(scroll, 50); setTimeout(scroll, 150); setTimeout(scroll, 350);
        })();
        </script>""",
        height=0,
    )
