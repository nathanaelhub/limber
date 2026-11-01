"""The therapist app's look, from the Limber design export (design/limber-export/screens/limber.css).

Every colour lives in the token block below; the rest of the stylesheet uses the tokens. The user's
accessibility settings (feature 016) re-define tokens rather than overriding individual rules, so every
component follows them.
"""

FONT_URL = "https://fonts.googleapis.com/css2?family=Sora:wght@400;500;600;700;800&display=swap"

TOKENS = """
:root {
  --teal: #0E6B64; --teal-dark: #0A544E; --coral: #F2684A; --ink: #16302C; --muted: #728280;
  --muted-text: #5E6E6C; --bg: #FAF8F4; --card: #FFFFFF; --side: #F1EEE7; --line: #EDEAE2;
  --line-strong: #D6D1C5; --teal-tint: #E3EFED; --coral-tint: #FDEBE5; --warn: #B4432B; --warn-tint: #FBECE8;
  --amber: #C98A1B; --on-teal: #FFFFFF; --badge-bg: var(--coral); --badge-fg: var(--ink);
  --bw: 1px; --r-card: 22px; --r-ctl: 14px;
  --font: "Sora", "Outfit", system-ui, -apple-system, "Segoe UI", sans-serif;
  --fs-xs: 13px; --fs-sm: 15px; --fs-body: 16px; --fs-h3: 18px; --fs-h2: 22px; --fs-h1: 30px;
}
"""

# Larger text, Higher contrast (AAA), Less motion: token swaps first, then the few rules tokens cannot reach.
PREF_CSS = {
    "larger_text": ":root { --fs-xs: 16px; --fs-sm: 18px; --fs-body: 20px; --fs-h3: 23px; --fs-h2: 26px; --fs-h1: 34px; }",
    "high_contrast": ":root { --teal: #0A544E; --muted: #16302C; --muted-text: #16302C; --line: #16302C; "
                     "--line-strong: #16302C; --bw: 2px; --teal-tint: #FFFFFF; --coral-tint: #FFFFFF; "
                     "--warn-tint: #FFFFFF; --badge-bg: #16302C; --badge-fg: #FFFFFF; --warn: #8E3220; "
                     "--bg: #FFFFFF; --side: #FFFFFF; }",
    "reduced_motion": "*, *::before, *::after { animation: none !important; transition: none !important; }",
}

STYLES = """
html, body, .stApp, .stApp button, .stApp input, .stApp textarea, .stApp select { font-family: var(--font); }
.stApp { background: var(--bg); color: var(--ink); }
.stApp, .stApp p, .stApp li, .stApp label, .stMarkdown p { font-size: var(--fs-body); }
.stApp h1, .stApp h2, .stApp h3 { color: var(--ink); letter-spacing: -0.02em; font-weight: 800; }
.stApp h1 { font-size: var(--fs-h1) !important; }
.stApp h2 { font-size: var(--fs-h2) !important; }
.stApp h3 { font-size: var(--fs-h3) !important; }
[data-testid="stCaptionContainer"], .stCaption, .stApp small { color: var(--muted-text) !important; font-size: var(--fs-xs); }
[data-testid="stCaptionContainer"] p { font-size: var(--fs-xs); color: var(--muted-text) !important; }
.stSelectbox [data-baseweb="select"] > div, .stTextInput [data-baseweb="input"], .stTextArea [data-baseweb="textarea"] {
  border: var(--bw) solid var(--line-strong) !important; }
.block-container { padding-top: 2.5rem; max-width: 1180px; }

/* Streamlit chrome: no Deploy button or main menu, the header stays only for the sidebar toggle. */
[data-testid="stAppDeployButton"], [data-testid="stMainMenu"], #MainMenu, [data-testid="stStatusWidget"] { display: none !important; }
[data-testid="stHeader"] { background: transparent; }

/* Sidebar: lockup, primary items, grouped tools. */
[data-testid="stSidebar"] { background: var(--side); border-right: var(--bw) solid var(--line); }
[data-testid="stSidebar"] .stButton button { justify-content: flex-start; min-height: 40px; padding: 0 12px;
  border-radius: 10px; font-size: var(--fs-sm); font-weight: 600; color: var(--ink); }
[data-testid="stSidebar"] .stButton button p { font-size: var(--fs-sm); }
[data-testid="stSidebar"] [data-testid="stBaseButton-tertiary"] { background: transparent; border: var(--bw) solid transparent; }
[data-testid="stSidebar"] [data-testid="stBaseButton-tertiary"]:hover { background: var(--card); color: var(--ink); }
[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"] { background: var(--card); border: var(--bw) solid var(--line); font-weight: 800; }
[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"] p { font-weight: 800; }
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap: 0.15rem; }
[data-testid="stSidebar"] .stMarkdownBadge { background: var(--badge-bg) !important; color: var(--badge-fg) !important;
  font-weight: 800; border-radius: 999px; padding: 0 8px; margin-left: 6px; }
[data-testid="stSidebar"] .stButton button > div { width: 100%; justify-content: flex-start; }
.st-key-nav_primary, .st-key-nav_tools, .st-key-nav_admin { gap: 2px !important; }
.limber-lockup { display: flex; align-items: center; gap: 0.55rem; padding: 4px 0 0; }
.limber-lockup svg { width: 34px; height: 34px; }
.limber-lockup span { font-size: 1.45rem; font-weight: 800; letter-spacing: -0.03em; color: var(--ink); }
.limber-tag { color: var(--muted-text); font-size: var(--fs-xs); margin: 2px 0 14px; }
.nav-group { color: var(--muted-text); font-size: 12px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase;
  margin: 16px 0 4px 12px; }

/* Buttons: primary teal, secondary outlined, 14px radius. */
.stButton button, .stDownloadButton button, .stFormSubmitButton button, [data-testid="stBaseButton-primary"],
[data-testid="stBaseButton-secondary"] { border-radius: var(--r-ctl); font-weight: 700; min-height: 40px; }
.stMain [data-testid="stBaseButton-secondary"], .stMain [data-testid="stBaseButton-secondaryFormSubmit"] {
  background: var(--card); color: var(--ink); border: var(--bw) solid var(--line-strong); }
.stMain [data-testid="stBaseButton-secondary"]:hover { border-color: var(--teal); color: var(--teal-dark); }
[data-testid="stBaseButton-primary"], [data-testid="stBaseButton-primaryFormSubmit"] {
  background: var(--teal); border: var(--bw) solid var(--teal); color: var(--on-teal); }
[data-testid="stBaseButton-primary"]:hover { background: var(--teal-dark); border-color: var(--teal-dark); }
.stMain button:disabled { background: var(--line) !important; color: var(--muted-text) !important; border-color: var(--line) !important; }

/* Cards, metrics, tabs, alerts, inputs, tables. */
.stMain div[data-testid="stVerticalBlock"][class*="st-key-card"] { background: var(--card); border-radius: var(--r-card);
  border: var(--bw) solid var(--line) !important; padding: 22px 24px; }
[data-testid="stMetric"] { background: var(--card); border: var(--bw) solid var(--line); border-radius: var(--r-card); padding: 16px 20px; }
[data-testid="stMetricLabel"] p { font-size: var(--fs-xs) !important; color: var(--muted-text); }
[data-testid="stMetricValue"] { font-weight: 800; color: var(--ink); letter-spacing: -0.02em; }
[data-testid="stTabs"] [role="tablist"] { gap: 28px; border-bottom: var(--bw) solid var(--line); }
[data-testid="stTab"] { padding: 10px 0; background: transparent; }
[data-testid="stTab"] p { font-size: var(--fs-sm); font-weight: 600; color: var(--ink); }
[data-testid="stTab"][aria-selected="true"] { box-shadow: inset 0 -3px 0 var(--teal); }
[data-testid="stTab"][aria-selected="true"] p { color: var(--teal-dark); font-weight: 800; }
[data-testid="stAlert"] > div { border-radius: var(--r-ctl); border: var(--bw) solid transparent; color: var(--ink); }
[data-testid="stAlertContentWarning"], [data-testid="stAlertContentError"] { color: var(--ink); }
div[data-testid="stAlert"]:has([data-testid="stAlertContentInfo"]) > div { background: var(--teal-tint); border-color: var(--line); }
div[data-testid="stAlert"]:has([data-testid="stAlertContentError"]) > div,
div[data-testid="stAlert"]:has([data-testid="stAlertContentWarning"]) > div { background: var(--warn-tint); border-color: var(--warn); }
div[data-testid="stAlert"]:has([data-testid="stAlertContentSuccess"]) > div { background: var(--teal-tint); border-color: var(--teal); }
.stTextInput input, .stTextArea textarea, .stNumberInput input, .stDateInput input, [data-baseweb="select"] > div {
  border-radius: var(--r-ctl) !important; }
.stTextArea textarea, .stTextInput input { color: var(--ink); font-size: var(--fs-body); }
[data-baseweb="input"], [data-baseweb="textarea"], [data-baseweb="select"] > div { border-color: var(--line-strong) !important; border-width: var(--bw) !important; }
[data-testid="stDataFrame"], [data-testid="stTable"] { border: var(--bw) solid var(--line); border-radius: var(--r-ctl); overflow: hidden; }
[data-testid="stExpander"] details { border: var(--bw) solid var(--line); border-radius: var(--r-ctl); background: var(--card); }
[data-testid="stChatMessage"] { background: transparent; padding: 8px 0; }
[data-testid="stChatMessage"] [data-testid="stVerticalBlock"] { gap: 0.3rem; }
[data-testid="stChatMessage"] [data-testid="stBaseButton-tertiary"] { min-height: 28px; padding: 0; color: var(--muted-text); font-size: var(--fs-xs); }
[data-testid="stChatMessage"] [data-testid="stBaseButton-tertiary"] p { font-size: var(--fs-xs); }
[data-testid="stChatMessageAvatarCustom"], [data-testid="stChatMessageAvatarUser"], [data-testid="stChatMessageAvatarAssistant"] {
  border-radius: 8px; }

/* The AI label: the boxed mark plus words, the same everywhere. */
.ai-label { white-space: nowrap; display: inline-flex; align-items: center; gap: 8px; font-size: var(--fs-xs); font-weight: 700; color: var(--ink); }
.ai-mark { display: inline-grid; place-items: center; height: 22px; min-width: 28px; padding: 0 5px; border: 1.5px solid var(--ink);
  border-radius: 6px; font-size: 11px; font-weight: 800; letter-spacing: .04em; line-height: 1; background: var(--card); color: var(--ink); }
.badge { display: inline-flex; align-items: center; padding: 2px 10px; border-radius: 999px; font-size: var(--fs-xs); font-weight: 700;
  border: var(--bw) solid; white-space: nowrap; line-height: 1.4; }
.badge.teal { color: var(--teal-dark); background: var(--teal-tint); border-color: var(--teal); }
.badge.warn { color: var(--warn); background: var(--warn-tint); border-color: var(--warn); }
.badge.count { color: var(--badge-fg); background: var(--badge-bg); border-color: var(--badge-bg); }
.ptitle-sub { color: var(--muted-text); font-size: var(--fs-sm); margin: -6px 0 6px; }

/* Older pages (dashboard, live session). */
p.main-header, .main-header { font-size: 2.6rem !important; line-height: 1.1; font-weight: 800 !important; letter-spacing: -0.03em;
  color: var(--ink); margin-bottom: 0.5rem; }
p.sub-header, .sub-header { font-size: 1.15rem !important; color: var(--muted-text); margin-bottom: 2rem; }
.metric-card { background: var(--card); border: var(--bw) solid var(--line); padding: 1rem; border-radius: 18px; text-align: center; }
.metric-value { font-size: 2rem; font-weight: 800; color: var(--teal); }
.metric-label { font-size: 0.9rem; color: var(--muted-text); }
.form-good { color: var(--teal); } .form-warning { color: var(--amber); } .form-poor { color: var(--coral); }
.stProgress > div > div > div > div { background-color: var(--teal); }
"""


def _one_block(css: str) -> str:
    """No blank lines: st.markdown ends an HTML block at a blank line, which would cut the stylesheet short."""
    return "\n".join(line for line in css.splitlines() if line.strip())


def base_css() -> str:
    """The stylesheet injected once per run, before any page renders."""
    return f'<link rel="stylesheet" href="{FONT_URL}"><style>{_one_block(TOKENS + STYLES)}</style>'


def pref_css(prefs, order) -> str:
    """The user's accessibility settings as one style block, or an empty string when none are on."""
    rules = " ".join(PREF_CSS[k] for k in order if prefs.get(k))
    return f"<style>{rules}</style>" if rules else ""


def ai_label(text: str) -> str:
    """HTML for the AI label: the boxed mark plus its words (the words are fixed strings, never model output)."""
    return f'<span class="ai-label"><span class="ai-mark">AI</span>{text}</span>'
