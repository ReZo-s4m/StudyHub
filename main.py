import streamlit as st
import streamlit.components.v1 as components
from lecture_processor import process_input, process_pdf
from auth import show_auth_page, is_authenticated, get_current_user, logout
from database import (
    init_db, save_study_note, get_user_notes, delete_study_note, get_user_stats,
    save_personal_note, get_personal_notes, delete_personal_note,
    get_or_create_local_user,
)
from firebase_auth import verify_session_cookie
import os, time, json, base64, tempfile, textwrap, threading, queue, re
from datetime import datetime, timedelta


def load_enhanced_css():
    css_path = os.path.join(os.path.dirname(__file__), "style.css")
    try:
        with open(css_path, encoding="utf-8") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
    except OSError:
        pass


def render_html(block: str):
    normalized = "\n".join(
        line.lstrip(" \t\u00A0") for line in textwrap.dedent(block).splitlines()
    ).strip()
    if hasattr(st, "html"):
        st.html(normalized)
    else:
        st.markdown(normalized, unsafe_allow_html=True)


def inject_dynamic_cursor():
        components.html(
                """
                <script>
                (() => {
                    try {
                        const doc = window.parent.document;
                        if (!doc || !doc.body) return;
                        if (!window.matchMedia('(pointer:fine)').matches) return;
                        if (doc.body.dataset.dynamicCursorReady === '1') return;
                        doc.body.dataset.dynamicCursorReady = '1';

                        if (!doc.getElementById('dynamic-cursor-style')) {
                            const style = doc.createElement('style');
                            style.id = 'dynamic-cursor-style';
                            style.textContent = `
                                html,body,.stApp{cursor:none!important;}
                                a,button,[role="button"],input,textarea,select,summary,label,[data-baseweb="tab"]{cursor:none!important;}
                                .cursor-dot,.cursor-ring{position:fixed;top:0;left:0;transform:translate(-50%,-50%);pointer-events:none;z-index:999999;}
                                .cursor-dot{width:10px;height:10px;border-radius:50%;background:#FFE067;box-shadow:0 0 0 2px rgba(18,13,42,.75),0 0 22px rgba(255,224,103,.8);transition:transform .1s ease;}
                                .cursor-ring{width:36px;height:36px;border-radius:50%;border:2px solid rgba(255,255,255,.9);box-shadow:0 8px 24px rgba(18,13,42,.28),inset 0 0 12px rgba(255,255,255,.2);backdrop-filter:blur(3px);transition:width .14s ease,height .14s ease,border-color .14s ease;}
                                .cursor-ring.active{width:48px;height:48px;border-color:#00C9A7;box-shadow:0 10px 30px rgba(0,201,167,.35),inset 0 0 14px rgba(255,255,255,.3);}
                                .cursor-dot.click{transform:translate(-50%,-50%) scale(.7);}
                            `;
                            doc.head.appendChild(style);
                        }

                        const dot = doc.createElement('div');
                        const ring = doc.createElement('div');
                        dot.className = 'cursor-dot';
                        ring.className = 'cursor-ring';
                        doc.body.appendChild(ring);
                        doc.body.appendChild(dot);

                        let mouseX = window.parent.innerWidth / 2;
                        let mouseY = window.parent.innerHeight / 2;
                        let ringX = mouseX;
                        let ringY = mouseY;

                        const loop = () => {
                            ringX += (mouseX - ringX) * 0.16;
                            ringY += (mouseY - ringY) * 0.16;
                            dot.style.left = mouseX + 'px';
                            dot.style.top = mouseY + 'px';
                            ring.style.left = ringX + 'px';
                            ring.style.top = ringY + 'px';
                            window.requestAnimationFrame(loop);
                        };
                        loop();

                        doc.addEventListener('mousemove', (e) => {
                            mouseX = e.clientX;
                            mouseY = e.clientY;
                        }, { passive: true });

                        const interactiveSelector = 'a, button, [role="button"], input, textarea, select, summary, label, [data-baseweb="tab"]';
                        doc.addEventListener('mouseover', (e) => {
                            if (e.target && e.target.closest && e.target.closest(interactiveSelector)) {
                                ring.classList.add('active');
                            }
                        });
                        doc.addEventListener('mouseout', (e) => {
                            if (e.target && e.target.closest && e.target.closest(interactiveSelector)) {
                                ring.classList.remove('active');
                            }
                        });

                        doc.addEventListener('mousedown', () => {
                            dot.classList.add('click');
                            ring.classList.add('active');
                        });
                        doc.addEventListener('mouseup', () => {
                            dot.classList.remove('click');
                        });
                    } catch (e) {
                        // no-op
                    }
                })();
                </script>
                """,
                height=0,
                width=0,
        )


st.set_page_config(
    page_title="Exam Study Hub Generator",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Initialize database on app startup
init_db()

load_enhanced_css()
inject_dynamic_cursor()

# =============================================
# FIREBASE SESSION RESTORATION (cookie-based)
# =============================================
# On each page load, check if the Firebase session cookie is present in the browser
# and valid. If so, restore the user's authenticated session.
FIREBASE_COOKIE_NAME = "firebase_session"


def _read_firebase_cookie_from_browser():
    """Read the firebase session cookie via JS interop and return its value."""
    import streamlit as st
    cookie_html = f"""
    <iframe id="cookie_reader_{id(st.session_state.get('rerun_count', 0))}"
        style="display:none;"
        srcdoc="<script>window.parent.postMessage({{type: 'get_cookie', name: '{FIREBASE_COOKIE_NAME}'}}, '*');</script>">
    </iframe>
    <script>
    window.addEventListener('message', function(event) {{
        if (event.data && event.data.type === 'get_cookie_response') {{
            window['firebase_cookie_value'] = event.data.value || '';
        }}
    }});
    // Attempt to read cookie via direct JS
    (function() {{
        const match = document.cookie.match(/(?:^|; ){FIREBASE_COOKIE_NAME}=([^;]*)/);
        window['firebase_cookie_value'] = match ? match[1] : '';
    }})();
    </script>
    """
    st.html(cookie_html)
    # Return the cookie value stored in session_state by the auth module
    return st.session_state.get("session_cookie", None)


# Try to restore auth from Firebase session cookie stored in session_state
if not is_authenticated():
    stored_cookie = st.session_state.get("session_cookie")
    if stored_cookie:
        is_valid, user_data = verify_session_cookie(stored_cookie)
        if is_valid and user_data:
            # Map Firebase user to local DB user (create record if first login)
            local_user_id, _ = get_or_create_local_user(
                firebase_uid=user_data["uid"],
                email=user_data["email"],
                name=user_data.get("name", ""),
            )
            user_data["id"] = local_user_id
            st.session_state.authenticated = True
            st.session_state.user = user_data
        else:
            # Cookie invalid or expired — clear it
            st.session_state.session_cookie = None
            if "user" in st.session_state:
                del st.session_state.user


# =============================================
# LANDING PAGE CSS (shared token)
# =============================================
LP_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Fredoka+One&family=Nunito:wght@400;500;600;700;800;900&display=swap');
:root{--yellow:#FFD60A;--yellow2:#FFEB5B;--purple:#6C3CE1;--coral:#FF6B6B;--mint:#00C9A7;--orange:#FF9F43;--cream:#F1ECDD;--dark:#1C1433;--dark2:#2D2150;}
html,body,.stApp{background:radial-gradient(circle at 12% 10%,#FFF8CE 0%,#F7EAA8 40%,#E7D57A 100%)!important;font-family:'Nunito',sans-serif;color:var(--dark);overflow-x:hidden;}
header[data-testid="stHeader"],footer,#MainMenu,section[data-testid="stSidebar"]{display:none!important;}
.block-container{padding:0!important;max-width:100%!important;}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0;}
.lp-nav{position:fixed;top:0;left:0;right:0;z-index:1000;display:flex;align-items:center;justify-content:space-between;padding:0 3.5rem;height:68px;background:linear-gradient(165deg,#ffffff 0%,#f6f4ff 100%);border-bottom:3px solid var(--dark);box-shadow:0 12px 24px rgba(28,20,51,.12),0 4px 0 var(--dark);}
.nav-logo{display:flex;align-items:center;gap:.6rem;font-family:'Fredoka One',cursive;font-size:1.55rem;color:var(--dark);text-decoration:none;}
.nav-logo .dot{color:var(--purple);}
.logo-icon{background:var(--yellow);width:38px;height:38px;border-radius:10px;border:2.5px solid var(--dark);display:flex;align-items:center;justify-content:center;font-size:1.2rem;box-shadow:3px 3px 0 var(--dark);}
.nav-links-row{display:flex;gap:2.5rem;list-style:none;}
.nav-links-row a{font-weight:700;font-size:.92rem;color:var(--dark);text-decoration:none;padding-bottom:2px;border-bottom:2px solid transparent;transition:border-color .2s;}
.nav-links-row a:hover{border-color:var(--purple);}
.nav-right-btns{display:flex;align-items:center;gap:.75rem;}
.lp-btn{font-family:'Nunito',sans-serif;font-weight:800;border-radius:14px;cursor:pointer;border:3px solid var(--dark);transition:transform .12s,box-shadow .12s;box-shadow:4px 4px 0 var(--dark);text-decoration:none;display:inline-block;white-space:nowrap;text-align:center;line-height:1;}
.lp-btn:hover{transform:translate(-2px,-2px);box-shadow:6px 6px 0 var(--dark);}
.lp-btn:active{transform:translate(2px,2px);box-shadow:2px 2px 0 var(--dark);}
.lp-btn-sm{font-size:.85rem;padding:.52rem 1.2rem;border-radius:10px;box-shadow:3px 3px 0 var(--dark);}
.lp-btn-md{font-size:1rem;padding:.85rem 2rem;}
.lp-btn-lg{font-size:1.05rem;padding:.92rem 2.3rem;}
.lp-btn-ghost{background:transparent;color:var(--dark);}
.lp-btn-ghost:hover{background:rgba(0,0,0,.05);}
.lp-btn-purple{background:var(--purple);color:#fff;}
.lp-btn-dark{background:var(--dark);color:var(--yellow);}
.lp-btn-white{background:#fff;color:var(--dark);}
.hero{min-height:100vh;background:linear-gradient(155deg,#FFF3A3 0%,var(--yellow) 45%,#FFCA3A 100%);display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:100px 2rem 5rem;position:relative;overflow:hidden;}
.hero::before{content:'';position:absolute;top:-80px;right:-80px;width:320px;height:320px;border-radius:50%;background:var(--purple);opacity:.12;}
.hero::after{content:'';position:absolute;bottom:-60px;left:-60px;width:240px;height:240px;border-radius:50%;background:var(--coral);opacity:.15;}
.shape{position:absolute;pointer-events:none;animation:floatY 4s ease-in-out infinite;}
@keyframes floatY{0%,100%{transform:translateY(0) rotate(0deg);}50%{transform:translateY(-18px) rotate(8deg);}}
.hero-chip{display:inline-flex;align-items:center;gap:.4rem;background:var(--dark);color:var(--yellow2);font-weight:800;font-size:.8rem;letter-spacing:1.2px;text-transform:uppercase;padding:.4rem 1.2rem;border-radius:50px;margin-bottom:1.8rem;animation:popIn .5s cubic-bezier(.34,1.56,.64,1) both;}
.hero-title{font-family:'Fredoka One',cursive;font-size:clamp(2.8rem,6.5vw,5.5rem);line-height:1.08;color:var(--dark);max-width:860px;margin-bottom:1.4rem;animation:popIn .55s cubic-bezier(.34,1.56,.64,1) .08s both;}
.hl-purple{color:var(--purple);background:white;padding:0 .12em;border-radius:8px;border:3px solid var(--dark);display:inline-block;transform:rotate(-1.5deg);}
.hl-coral{color:var(--coral);}
.hero-sub{font-size:1.1rem;font-weight:600;color:var(--dark2);max-width:540px;line-height:1.7;margin-bottom:2.4rem;opacity:.85;animation:popIn .55s cubic-bezier(.34,1.56,.64,1) .16s both;}
.hero-cta-row{display:flex;gap:1rem;justify-content:center;align-items:center;flex-wrap:wrap;animation:popIn .55s cubic-bezier(.34,1.56,.64,1) .24s both;}
.stats-strip{background:var(--dark);color:#fff;display:flex;justify-content:center;flex-wrap:wrap;border-top:3px solid var(--dark);border-bottom:3px solid var(--dark);}
.stat-box{flex:1;min-width:150px;text-align:center;padding:2rem 1.5rem;border-right:2px solid rgba(255,255,255,.1);}
.stat-box:last-child{border-right:none;}
.stat-num{font-family:'Fredoka One',cursive;font-size:2.5rem;color:var(--yellow);display:block;line-height:1;margin-bottom:.3rem;}
.stat-label{font-size:.8rem;opacity:.6;font-weight:600;}
.section{padding:6rem 2rem;}
.section-inner{max-width:1160px;margin:0 auto;}
.section-eyebrow{font-weight:900;font-size:.72rem;letter-spacing:2.5px;text-transform:uppercase;color:var(--purple);margin-bottom:.7rem;display:block;}
.section-title{font-family:'Fredoka One',cursive;font-size:clamp(1.9rem,3.8vw,3rem);color:var(--dark);margin-bottom:.8rem;line-height:1.1;}
.section-sub{font-size:1rem;color:#555;max-width:500px;line-height:1.7;font-weight:500;}
.features-bg{background:#fff;border-top:3px solid var(--dark);border-bottom:3px solid var(--dark);}
.features-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:1.5rem;margin-top:3.5rem;}
.feat-card{border-radius:20px;padding:2rem;border:3px solid var(--dark);box-shadow:0 14px 26px rgba(28,20,51,.14),6px 6px 0 var(--dark);transition:transform .15s,box-shadow .15s;}
.feat-card:hover{transform:translate(-3px,-3px);box-shadow:0 18px 30px rgba(28,20,51,.2),9px 9px 0 var(--dark);}
.feat-card.c1{background:var(--yellow2)}.feat-card.c2{background:#E0D5FF}.feat-card.c3{background:#FFD5D5}
.feat-card.c4{background:#C8F7EE}.feat-card.c5{background:#FFE5C2}.feat-card.c6{background:#D0EEFF}
.feat-icon{font-size:2.4rem;margin-bottom:1rem;display:block;}
.feat-card h3{font-family:'Fredoka One',cursive;font-size:1.3rem;color:var(--dark);margin-bottom:.5rem;}
.feat-card p{font-size:.9rem;color:#444;line-height:1.65;font-weight:500;}
.feat-tag{display:inline-block;margin-top:1rem;background:var(--dark);color:#fff;font-size:.7rem;font-weight:800;letter-spacing:.5px;padding:.25rem .75rem;border-radius:50px;}
.how-bg{background:var(--purple);}
.how-bg .section-eyebrow{color:var(--yellow2);}
.how-bg .section-title{color:#fff;}
.steps-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:1.5rem;margin-top:3.5rem;}
.step-card{background:rgba(255,255,255,.1);border:2.5px solid rgba(255,255,255,.25);border-radius:20px;padding:2rem;text-align:center;transition:background .2s;}
.step-card:hover{background:rgba(255,255,255,.18);}
.step-num-box{width:54px;height:54px;border-radius:14px;background:var(--yellow);border:2.5px solid var(--dark);box-shadow:4px 4px 0 var(--dark);font-family:'Fredoka One',cursive;font-size:1.4rem;color:var(--dark);display:flex;align-items:center;justify-content:center;margin:0 auto 1.2rem;}
.step-card h4{font-family:'Fredoka One',cursive;font-size:1.15rem;color:#fff;margin-bottom:.5rem;}
.step-card p{font-size:.87rem;color:rgba(255,255,255,.72);line-height:1.6;}
.testi-bg{background:var(--cream);}
.testi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(290px,1fr));gap:1.5rem;margin-top:3.5rem;}
.testi-card{background:linear-gradient(165deg,#fff 0%,#f6f7ff 100%);border:3px solid var(--dark);border-radius:20px;padding:1.8rem;box-shadow:0 12px 24px rgba(28,20,51,.14),5px 5px 0 var(--dark);transition:transform .15s,box-shadow .15s;}
.testi-card:hover{transform:translate(-2px,-2px);box-shadow:0 16px 30px rgba(28,20,51,.2),7px 7px 0 var(--dark);}
.testi-stars{font-size:1rem;color:var(--orange);margin-bottom:1rem;letter-spacing:2px;}
.testi-text{font-size:.93rem;line-height:1.7;color:#333;font-weight:600;margin-bottom:1.4rem;font-style:italic;}
.testi-author{display:flex;align-items:center;gap:.75rem;}
.testi-av{width:42px;height:42px;border-radius:12px;border:2.5px solid var(--dark);display:flex;align-items:center;justify-content:center;font-family:'Fredoka One',cursive;font-size:1rem;color:#fff;flex-shrink:0;}
.testi-name{font-weight:800;font-size:.88rem;color:var(--dark);}
.testi-role{font-size:.75rem;color:#888;font-weight:600;}
.cta-bg{background:linear-gradient(165deg,#FF8179 0%,var(--coral) 55%,#FF5A72 100%);border-top:3px solid var(--dark);border-bottom:3px solid var(--dark);text-align:center;padding:5.5rem 2rem;}
.cta-bg .section-title{color:#fff;}
.cta-sub{font-size:1.05rem;color:rgba(255,255,255,.88);font-weight:600;max-width:500px;margin:.8rem auto 2.5rem;line-height:1.65;}
.cta-btn-row{display:flex;justify-content:center;align-items:center;gap:1rem;flex-wrap:nowrap;}
.lp-footer{background:var(--dark);color:rgba(255,255,255,.55);display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:1rem;padding:1.8rem 3.5rem;font-size:.82rem;font-weight:600;}
.footer-logo{font-family:'Fredoka One',cursive;font-size:1.1rem;color:var(--yellow);}
.footer-links{display:flex;gap:1.5rem;}
.footer-links a{color:rgba(255,255,255,.45);text-decoration:none;transition:color .2s;}
.footer-links a:hover{color:var(--yellow2);}
@keyframes popIn{from{opacity:0;transform:scale(.88) translateY(20px);}to{opacity:1;transform:scale(1) translateY(0);}}
</style>
"""

# =============================================
# MAIN APP CSS — Neo-brutalist bright theme
# =============================================
APP_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Fredoka+One&family=Nunito:wght@400;500;600;700;800;900&display=swap');
:root{--yellow:#FFE067;--yellow2:#FFF3A6;--purple:#6C3CE1;--coral:#FF6B6B;--mint:#00C9A7;--orange:#FF9F43;--cream:#F4F7FF;--dark:#120D2A;--dark2:#2B2464;--depth-bg:#95A6FF;--surface:#ECF1FF;}

/* ── BASE ── */
html,body{background:radial-gradient(circle at 18% 15%, #C8D2FF 0%, var(--depth-bg) 42%, #7F92F9 100%)!important;height:100%!important;overflow:hidden!important;}
.stApp,.main,.block-container{background:transparent!important;font-family:'Nunito',sans-serif!important;color:var(--dark)!important;}
.stApp [data-testid="stAppViewContainer"]{background:transparent!important;height:100vh!important;overflow-y:auto!important;overflow-x:hidden!important;perspective:1000px;}
.stApp [data-testid="stHeader"]{background:transparent!important;}
p,div,li,td,th{font-family:'Nunito',sans-serif!important;}

@media (pointer:fine){
    html,body,.stApp{cursor:none!important;}
    a,button,[role="button"],input,textarea,label,summary,[data-baseweb="tab"]{cursor:none!important;}
}

.cursor-dot,.cursor-ring{
    position:fixed;
    top:0;
    left:0;
    pointer-events:none;
    z-index:99999;
    transform:translate(-50%,-50%);
    transition:opacity .2s ease;
}

.cursor-dot{
    width:10px;
    height:10px;
    border-radius:50%;
    background:var(--yellow);
    box-shadow:0 0 0 2px rgba(18,13,42,.75),0 0 22px rgba(255,224,103,.8);
}

.cursor-ring{
    width:36px;
    height:36px;
    border-radius:50%;
    border:2px solid rgba(255,255,255,.9);
    box-shadow:0 8px 24px rgba(18,13,42,.28),inset 0 0 12px rgba(255,255,255,.2);
    backdrop-filter:blur(3px);
}

.cursor-ring.active{
    width:48px;
    height:48px;
    border-color:var(--mint);
    box-shadow:0 10px 30px rgba(0,201,167,.35),inset 0 0 14px rgba(255,255,255,.3);
}

.cursor-dot.click{
    transform:translate(-50%,-50%) scale(.7);
}
/* Keep Streamlit Material icons from being overridden by global font rules */
span.material-symbols-rounded,
span.material-symbols-outlined,
span.material-symbols-sharp,
span.material-icons,
span.material-icons-round,
span.material-icons-outlined,
span.material-icons-sharp,
[class*="material-symbol"],
[class*="material-icons"],
[data-testid="stSidebarCollapsedControl"] .material-symbols-rounded,
[data-testid="stSidebar"] button[kind="header"] .material-symbols-rounded,
[data-testid="stExpander"] .material-symbols-rounded{
    font-family:'Material Symbols Rounded','Material Symbols Outlined','Material Icons'!important;
    font-weight:normal!important;
    font-style:normal!important;
    letter-spacing:normal!important;
    text-transform:none!important;
    white-space:nowrap!important;
    direction:ltr!important;
    -webkit-font-smoothing:antialiased!important;
}

/* ── TOP-LEFT SIDEBAR TOGGLE VISIBILITY ── */
[data-testid="stSidebarCollapsedControl"]{
    background:var(--dark)!important;
    border:3px solid var(--dark)!important;
    border-radius:12px!important;
    box-shadow:4px 4px 0 var(--dark)!important;
    padding:.2rem!important;
    top:.65rem!important;
    left:.65rem!important;
}
[data-testid="stSidebarCollapsedControl"]:hover{
    background:#000!important;
    transform:translate(-1px,-1px)!important;
    box-shadow:6px 6px 0 var(--dark)!important;
}
[data-testid="stSidebarCollapsedControl"] button{
    width:2rem!important;
    height:2rem!important;
    display:flex!important;
    align-items:center!important;
    justify-content:center!important;
    background:transparent!important;
    color:var(--yellow)!important;
}
[data-testid="stSidebarCollapsedControl"] button [class*="material-symbol"],
[data-testid="stSidebarCollapsedControl"] button .material-icons,
[data-testid="stSidebarCollapsedControl"] button .material-icons-round,
[data-testid="stSidebarCollapsedControl"] button .material-icons-outlined{
    color:var(--yellow)!important;
    font-size:1.35rem!important;
    font-variation-settings:'FILL' 1,'wght' 700,'GRAD' 0,'opsz' 24;
}

/* ── SIDEBAR ── */
section[data-testid="stSidebar"]{background:linear-gradient(165deg,#8EA2FF 0%,#6F86F5 100%)!important;border-right:3px solid var(--dark)!important;box-shadow:8px 0 24px rgba(18,13,42,.22),4px 0 0 var(--dark)!important;}
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] span,
section[data-testid="stSidebar"] div,
section[data-testid="stSidebar"] label,
section[data-testid="stSidebar"] small{color:var(--dark)!important;}
section[data-testid="stSidebar"] .stButton>button{background:var(--dark)!important;color:var(--yellow)!important;border:2.5px solid var(--dark)!important;border-radius:12px!important;box-shadow:4px 4px 0 rgba(28,20,51,.3)!important;font-family:'Nunito',sans-serif!important;font-weight:800!important;font-size:.9rem!important;}
section[data-testid="stSidebar"] .stButton>button:hover{transform:translate(-2px,-2px)!important;box-shadow:6px 6px 0 rgba(28,20,51,.3)!important;}
section[data-testid="stSidebar"] .stButton>button span,
section[data-testid="stSidebar"] .stButton>button p,
section[data-testid="stSidebar"] .stButton>button div{
    color:var(--yellow)!important;
    opacity:1!important;
}
section[data-testid="stSidebar"] .stButton>button:hover span,
section[data-testid="stSidebar"] .stButton>button:hover p,
section[data-testid="stSidebar"] .stButton>button:hover div{
    color:#fff!important;
}
section[data-testid="stSidebar"] [data-testid="stMetric"]{background:#fff!important;border:2px solid var(--dark)!important;border-radius:12px!important;box-shadow:3px 3px 0 var(--dark)!important;padding:.6rem!important;}
section[data-testid="stSidebar"] [data-testid="stMetricValue"]{font-family:'Fredoka One',cursive!important;color:var(--purple)!important;font-size:1.4rem!important;}
section[data-testid="stSidebar"] [data-testid="stMetricLabel"]{color:var(--dark)!important;font-weight:700!important;}

/* ── PROFILE CARD ── */
.profile-card{background:linear-gradient(145deg,#7446E8 0%,#5D34D8 100%)!important;border:3px solid var(--dark)!important;border-radius:18px!important;box-shadow:0 12px 24px rgba(18,13,42,.22),5px 5px 0 var(--dark)!important;padding:1.2rem!important;display:flex;align-items:center;gap:.8rem;transform:translateZ(10px);}
.profile-avatar{background:var(--yellow)!important;color:var(--dark)!important;border:2.5px solid var(--dark)!important;box-shadow:3px 3px 0 var(--dark)!important;border-radius:12px!important;width:44px;height:44px;display:flex;align-items:center;justify-content:center;font-family:'Fredoka One',cursive!important;font-size:1.1rem!important;font-weight:900!important;}
.profile-name{color:#fff!important;font-weight:800!important;font-size:.9rem!important;margin:0!important;}
.profile-email{color:rgba(255,255,255,.7)!important;font-size:.75rem!important;margin:0!important;}
.profile-status{color:#7FFFD4!important;font-size:.75rem!important;font-weight:700!important;}

/* ── MAIN HEADER ── */
.main-header{background:linear-gradient(145deg,var(--yellow2) 0%,var(--yellow) 52%,#FFD84A 100%)!important;border:3px solid var(--dark)!important;border-radius:20px!important;box-shadow:0 16px 30px rgba(18,13,42,.24),6px 6px 0 var(--dark)!important;padding:2.5rem 2rem 2rem!important;margin-bottom:1.5rem!important;text-align:center;position:relative;overflow:hidden;transform:translateZ(16px);}
.main-title{font-family:'Fredoka One','Segoe UI Emoji','Noto Color Emoji',cursive!important;font-size:clamp(1.8rem,3.5vw,2.8rem)!important;color:var(--coral)!important;background:none!important;background-image:none!important;-webkit-text-fill-color:var(--coral)!important;margin-bottom:.4rem!important;}.subtitle{font-size:1rem!important;font-weight:700!important;color:var(--dark)!important;opacity:.75!important;}
.glow-badge{display:inline-block;background:var(--purple)!important;color:#fff!important;font-weight:800!important;font-size:.8rem!important;letter-spacing:.5px!important;padding:.35rem 1.1rem!important;border-radius:50px!important;border:2px solid var(--dark)!important;box-shadow:3px 3px 0 var(--dark)!important;}

/* ── TABS ── */
.stTabs [data-baseweb="tab-list"]{background:linear-gradient(180deg,#fff 0%,var(--surface) 100%)!important;border:3px solid var(--dark)!important;border-radius:16px!important;box-shadow:0 12px 24px rgba(18,13,42,.18),4px 4px 0 var(--dark)!important;padding:.3rem!important;gap:.3rem!important;transform:translateZ(6px);}
.stTabs [data-baseweb="tab"]{background:transparent!important;color:var(--dark)!important;font-family:'Nunito',sans-serif!important;font-weight:800!important;border-radius:12px!important;border:2px solid transparent!important;transition:all .15s!important;}
.stTabs [data-baseweb="tab"] p,.stTabs [data-baseweb="tab"] span{color:var(--dark)!important;font-weight:800!important;}
.stTabs [aria-selected="true"]{background:linear-gradient(155deg,#7B55EA 0%,var(--purple) 100%)!important;border:2px solid var(--dark)!important;box-shadow:0 10px 18px rgba(108,60,225,.35),3px 3px 0 var(--dark)!important;transform:translateY(-1px);}
.stTabs [aria-selected="true"] p,.stTabs [aria-selected="true"] span{color:#fff!important;}

/* ── BUTTONS ── */
.stButton>button{font-family:'Nunito',sans-serif!important;font-weight:900!important;background:linear-gradient(160deg,#2E2261 0%,var(--dark) 100%)!important;color:var(--yellow)!important;border:3px solid var(--dark)!important;border-radius:14px!important;box-shadow:0 10px 22px rgba(18,13,42,.22),4px 4px 0 rgba(28,20,51,.3)!important;transition:transform .12s,box-shadow .12s,filter .12s!important;font-size:.9rem!important;}
.stButton>button:hover{transform:translate(-2px,-2px)!important;box-shadow:0 14px 26px rgba(108,60,225,.28),6px 6px 0 rgba(28,20,51,.3)!important;background:linear-gradient(160deg,#7B55EA 0%,var(--purple) 100%)!important;color:#fff!important;filter:saturate(1.08);}
.stButton>button:active{transform:translate(2px,2px)!important;box-shadow:2px 2px 0 rgba(28,20,51,.3)!important;}
.stButton>button[kind="primary"]{background:linear-gradient(155deg,#845CF0 0%,var(--purple) 100%)!important;color:#fff!important;}
.stButton>button[kind="primary"]:hover{background:var(--dark)!important;color:var(--yellow)!important;}

/* ── TEXT INPUTS ── */
.stTextInput>div>div>input,.stTextArea>div>div>textarea{background:#fff!important;color:var(--dark)!important;border:2.5px solid var(--dark)!important;border-radius:12px!important;box-shadow:4px 4px 0 rgba(28,20,51,.2)!important;font-family:'Nunito',sans-serif!important;font-weight:700!important;transition:transform .12s,box-shadow .12s!important;}
.stTextInput>div>div>input:focus,.stTextArea>div>div>textarea:focus{transform:translate(-2px,-2px)!important;box-shadow:6px 6px 0 var(--dark)!important;outline:none!important;}
.stTextInput>div>div>input::placeholder,.stTextArea>div>div>textarea::placeholder{color:#aaa!important;font-weight:500!important;}

/* ── ALL LABELS ── */
label,.stTextInput label,.stTextArea label,.stSelectbox label,.stFileUploader label,[data-testid="stWidgetLabel"]{font-family:'Nunito',sans-serif!important;font-weight:800!important;color:var(--dark)!important;font-size:.85rem!important;text-transform:uppercase!important;letter-spacing:.5px!important;}

/* ── SELECTBOX ── */
.stSelectbox>div>div,.stSelectbox [data-baseweb="select"]{background:#fff!important;border:2.5px solid var(--dark)!important;border-radius:12px!important;box-shadow:3px 3px 0 rgba(28,20,51,.2)!important;color:var(--dark)!important;}
.stSelectbox [data-baseweb="select"] span,.stSelectbox [data-baseweb="select"] div{color:var(--dark)!important;font-weight:700!important;}
.stSelectbox [data-baseweb="select"]>div,
.stSelectbox [data-baseweb="select"] input,
.stSelectbox [data-baseweb="select"] [role="combobox"]{
    background:#fff!important;
    color:var(--dark)!important;
}
.stSelectbox [data-baseweb="select"] svg{color:var(--dark)!important;fill:var(--dark)!important;}
[data-testid="stSelectbox"] [data-baseweb="select"],
[data-testid="stSelectbox"] [data-baseweb="select"]>div,
[data-testid="stSelectbox"] [data-baseweb="select"]>div>div,
[data-testid="stSelectbox"] [data-baseweb="select"] [role="combobox"],
[data-testid="stSelectbox"] [data-baseweb="select"] input{
    background:#fff!important;
    color:var(--dark)!important;
}
[data-testid="stSelectbox"] [data-baseweb="select"]:focus-within{
    background:#fff!important;
}
[data-baseweb="popover"],
[data-baseweb="popover"] [role="listbox"],
[data-baseweb="popover"] [role="option"]{
    background:#fff!important;
    color:var(--dark)!important;
}

/* ── RADIO BUTTONS — full fix ── */
.stRadio>div{gap:.6rem!important;flex-direction:row!important;flex-wrap:wrap!important;}
/* The outer label wrapper */
.stRadio [data-testid="stWidgetLabel"]{text-transform:uppercase!important;letter-spacing:.5px!important;font-weight:800!important;color:var(--dark)!important;font-size:.85rem!important;margin-bottom:.4rem!important;}
/* Each radio option pill */
.stRadio label{background:#fff!important;border:2.5px solid var(--dark)!important;border-radius:10px!important;box-shadow:3px 3px 0 rgba(28,20,51,.25)!important;padding:.45rem 1.1rem!important;cursor:pointer!important;transition:all .12s!important;display:inline-flex!important;align-items:center!important;gap:.5rem!important;}
.stRadio label:hover{transform:translate(-1px,-1px)!important;box-shadow:4px 4px 0 rgba(28,20,51,.25)!important;}
/* Text inside each radio pill */
.stRadio label p,
.stRadio label span,
.stRadio label div[data-testid="stMarkdownContainer"] p{color:var(--dark)!important;font-weight:700!important;font-size:.92rem!important;margin:0!important;line-height:1.2!important;}
/* Checked radio pill */
.stRadio label:has(input:checked){background:var(--purple)!important;border-color:var(--dark)!important;box-shadow:4px 4px 0 rgba(28,20,51,.3)!important;transform:translate(-2px,-2px)!important;}
/* Text inside CHECKED radio pill — must be white */
.stRadio label:has(input:checked) p,
.stRadio label:has(input:checked) span,
.stRadio label:has(input:checked) div[data-testid="stMarkdownContainer"] p{color:#fff!important;font-weight:800!important;}
/* Hide the actual radio circle dot */
.stRadio label input[type="radio"]{width:0!important;height:0!important;opacity:0!important;position:absolute!important;}

/* ── SUMMARY LENGTH SLIDER ── */
div[data-testid="stSelectSlider"]{
    max-width:420px!important;
}
div[data-testid="stSelectSlider"] [data-baseweb="slider"] > div > div{
    height:8px!important;
    border-radius:999px!important;
}
div[data-testid="stSelectSlider"] [data-baseweb="slider"] [role="slider"]{
    width:16px!important;
    height:16px!important;
    border:2px solid var(--dark)!important;
    box-shadow:2px 2px 0 var(--dark)!important;
}

/* ── FILE UPLOADER — full fix ── */
[data-testid="stFileUploader"]{border-radius:18px!important;}
[data-testid="stFileUploader"] section,
[data-testid="stFileUploader"]>div,
[data-testid="stFileUploader"] [data-testid="stFileUploaderDropzone"]{background:#fff!important;border:3px dashed var(--dark)!important;border-radius:18px!important;box-shadow:5px 5px 0 rgba(28,20,51,.25)!important;transition:transform .15s,box-shadow .15s!important;}
[data-testid="stFileUploader"] section:hover,
[data-testid="stFileUploader"]>div:hover{transform:translate(-2px,-2px)!important;box-shadow:7px 7px 0 rgba(28,20,51,.25)!important;border-color:var(--purple)!important;}
/* ALL text inside file uploader */
[data-testid="stFileUploader"] *{color:var(--dark)!important;}
[data-testid="stFileUploader"] span,
[data-testid="stFileUploader"] p,
[data-testid="stFileUploader"] small,
[data-testid="stFileUploader"] div{color:var(--dark)!important;font-weight:600!important;}
/* Browse files button inside uploader */
[data-testid="stFileUploader"] button,[data-testid="stFileUploaderDropzone"] button{background:var(--dark)!important;color:var(--yellow)!important;border:2.5px solid var(--dark)!important;border-radius:10px!important;box-shadow:3px 3px 0 rgba(28,20,51,.3)!important;font-weight:800!important;font-family:'Nunito',sans-serif!important;font-size:.85rem!important;}
[data-testid="stFileUploader"] button:hover{background:var(--purple)!important;color:#fff!important;}

/* ── GLASS CONTAINERS ── */
.glass-container{background:linear-gradient(170deg,#fff 0%,var(--surface) 100%)!important;border:3px solid var(--dark)!important;border-radius:20px!important;box-shadow:0 16px 30px rgba(18,13,42,.18),6px 6px 0 var(--dark)!important;padding:1.8rem!important;margin-bottom:1.2rem!important;transition:transform .15s,box-shadow .15s!important;transform-style:preserve-3d;}
.glass-container:hover{transform:translate(-2px,-3px)!important;box-shadow:0 20px 36px rgba(18,13,42,.24),8px 8px 0 var(--dark)!important;}

/* ── RESULTS HEADER ── */
.results-header{background:var(--mint)!important;border:3px solid var(--dark)!important;border-radius:18px!important;box-shadow:6px 6px 0 var(--dark)!important;padding:1.5rem 2rem!important;margin-bottom:1.2rem!important;}
.results-title{font-family:'Fredoka One',cursive!important;font-size:1.5rem!important;color:var(--dark)!important;}

/* ── SUMMARY CARD ── */
.summary-card{background:linear-gradient(155deg,#FFF5BB 0%,var(--yellow2) 100%)!important;border:3px solid var(--dark)!important;border-radius:18px!important;box-shadow:0 14px 26px rgba(18,13,42,.15),5px 5px 0 var(--dark)!important;padding:1.5rem!important;margin-bottom:1rem!important;}
.summary-card-header{display:flex;align-items:baseline;gap:1rem;margin-bottom:0;}
.summary-card-title{font-family:'Fredoka One',cursive!important;font-size:1.4rem!important;color:var(--dark)!important;margin:0!important;}
.summary-meta{font-size:.78rem!important;font-weight:700!important;color:var(--purple)!important;text-transform:uppercase!important;letter-spacing:.6px!important;}
.quick-summary-body{background:#fff!important;border:2.5px solid var(--dark)!important;border-radius:14px!important;box-shadow:4px 4px 0 var(--dark)!important;}
.quick-summary-body p{color:var(--dark)!important;}

/* ── SESSION ITEMS ── */
.session-item{display:flex;align-items:flex-start;gap:1rem;background:linear-gradient(165deg,#fff 0%,var(--surface) 100%)!important;border:2.5px solid var(--dark)!important;border-radius:14px!important;box-shadow:0 12px 24px rgba(18,13,42,.12),4px 4px 0 var(--dark)!important;padding:1rem 1.2rem!important;margin-bottom:.75rem!important;transition:transform .12s,box-shadow .12s!important;}
.session-item:hover{transform:translate(-2px,-2px)!important;box-shadow:0 16px 28px rgba(18,13,42,.18),6px 6px 0 var(--dark)!important;}
.session-number{background:var(--purple)!important;color:#fff!important;font-family:'Fredoka One',cursive!important;font-size:1rem!important;width:32px;height:32px;border-radius:8px;border:2px solid var(--dark)!important;box-shadow:2px 2px 0 var(--dark)!important;display:flex;align-items:center;justify-content:center;flex-shrink:0;}
.session-item strong{color:var(--dark)!important;font-weight:800!important;}

/* ── DETAILED ITEMS ── */
.detailed-item{display:flex;gap:.8rem;align-items:flex-start;background:#fff!important;border:2px solid var(--dark)!important;border-radius:12px!important;box-shadow:3px 3px 0 var(--dark)!important;padding:.9rem 1rem!important;margin-bottom:.6rem!important;}
.detailed-item-bar{width:4px;border-radius:4px;flex-shrink:0;align-self:stretch;background:var(--purple)!important;}

/* ── TAKEAWAYS ── */
.takeaway-item{display:flex;align-items:flex-start;gap:1rem;background:linear-gradient(165deg,#fff 0%,var(--surface) 100%)!important;border:2.5px solid var(--dark)!important;border-radius:14px!important;box-shadow:0 12px 24px rgba(18,13,42,.12),4px 4px 0 var(--dark)!important;padding:1rem 1.2rem!important;margin-bottom:.7rem!important;transition:transform .12s,box-shadow .12s!important;}
.takeaway-item:hover{transform:translate(-2px,-2px)!important;box-shadow:0 16px 28px rgba(18,13,42,.18),6px 6px 0 var(--dark)!important;}
.takeaway-number{background:var(--coral)!important;color:#fff!important;font-family:'Fredoka One',cursive!important;font-size:.95rem!important;width:30px;height:30px;border-radius:8px;border:2px solid var(--dark)!important;box-shadow:2px 2px 0 var(--dark)!important;display:flex;align-items:center;justify-content:center;flex-shrink:0;}
.takeaway-text{color:var(--dark)!important;font-weight:600!important;line-height:1.6;}

/* ── FLASHCARDS ── */
.fc-stats-bar{display:flex;gap:.75rem;flex-wrap:wrap;margin-bottom:1.2rem!important;}
.fc-stat{font-size:.82rem!important;font-weight:800!important;padding:.35rem .9rem!important;border-radius:50px!important;border:2px solid var(--dark)!important;box-shadow:2px 2px 0 var(--dark)!important;}
.fc-stat-mastered{background:#C8F7EE!important;color:var(--dark)!important;}
.fc-stat-learning{background:#FFE5C2!important;color:var(--dark)!important;}
.fc-stat-new{background:#E0D5FF!important;color:var(--dark)!important;}
.fc-card{background:linear-gradient(170deg,#fff 0%,var(--surface) 100%)!important;border:3px solid var(--dark)!important;border-radius:18px!important;box-shadow:0 16px 28px rgba(18,13,42,.15),5px 5px 0 var(--dark)!important;padding:1.4rem!important;margin-bottom:1rem!important;transition:transform .12s,box-shadow .12s!important;}
.fc-card:hover{transform:translate(-2px,-2px)!important;box-shadow:0 20px 34px rgba(18,13,42,.2),7px 7px 0 var(--dark)!important;}
.fc-card-top{display:flex;justify-content:space-between;align-items:center;margin-bottom:.8rem;}
.fc-card-num{font-size:.75rem!important;font-weight:800!important;color:#777!important;text-transform:uppercase!important;letter-spacing:.5px!important;}
.flashcard-status{font-size:.72rem!important;font-weight:800!important;color:#fff!important;padding:.2rem .65rem!important;border-radius:50px!important;border:1.5px solid var(--dark)!important;}
.fc-card-question{color:var(--dark)!important;font-weight:700!important;line-height:1.6;margin:0!important;}
.flashcard-answer{background:var(--yellow2)!important;border:2.5px solid var(--dark)!important;border-radius:14px!important;box-shadow:3px 3px 0 var(--dark)!important;padding:1rem 1.2rem!important;margin-bottom:.8rem!important;}
.flashcard-answer p{color:var(--dark)!important;}

/* ── CHECKBOX ── */
.stCheckbox label,.stCheckbox label span,.stCheckbox label p{color:var(--dark)!important;font-family:'Nunito',sans-serif!important;font-weight:700!important;}

/* ── PERSONAL NOTES ── */
.personal-note{background:#fff!important;border:2.5px solid var(--dark)!important;border-radius:14px!important;box-shadow:4px 4px 0 var(--dark)!important;padding:1rem 1.2rem!important;margin-bottom:.6rem!important;}
.note-timestamp{font-size:.72rem!important;font-weight:700!important;color:#888!important;text-transform:uppercase!important;letter-spacing:.5px!important;}

/* ── CONTENT NAV ── */
.content-nav{display:flex;flex-direction:column;gap:.4rem;margin-top:.5rem;}
.content-nav-item{display:flex;justify-content:space-between;align-items:center;background:#fff!important;border:2px solid var(--dark)!important;border-radius:10px!important;box-shadow:2px 2px 0 var(--dark)!important;padding:.5rem .8rem!important;font-size:.83rem!important;font-weight:700!important;color:var(--dark)!important;}
.nav-badge{background:var(--purple)!important;color:#fff!important;font-size:.7rem!important;font-weight:800!important;padding:.15rem .5rem!important;border-radius:50px!important;border:1.5px solid var(--dark)!important;}

/* ── ALERTS ── */
.stAlert{border:2.5px solid var(--dark)!important;border-radius:14px!important;box-shadow:4px 4px 0 var(--dark)!important;font-family:'Nunito',sans-serif!important;font-weight:700!important;}
.stAlert p,.stAlert span{color:var(--dark)!important;font-weight:700!important;}

/* ── EXPANDER ── */
.streamlit-expanderHeader,details summary{background:#fff!important;border:2.5px solid var(--dark)!important;border-radius:12px!important;box-shadow:3px 3px 0 var(--dark)!important;font-family:'Nunito',sans-serif!important;font-weight:800!important;color:var(--dark)!important;padding:.7rem 1rem!important;}
.streamlit-expanderContent{background:var(--cream)!important;border:2px solid var(--dark)!important;border-top:none!important;border-radius:0 0 12px 12px!important;padding:.5rem .4rem!important;}
.streamlit-expanderContent .stButton>button{background:#fff!important;color:var(--dark)!important;border:1.5px solid var(--dark)!important;box-shadow:2px 2px 0 var(--dark)!important;border-radius:10px!important;padding:.38rem .8rem!important;font-size:.85rem!important;}
.streamlit-expanderContent .stButton>button:hover{background:var(--yellow2)!important;color:var(--dark)!important;transform:translate(-1px,-1px)!important;box-shadow:3px 3px 0 var(--dark)!important;}
[data-testid="stExpanderDetails"]{
    background:#D8E2FF!important;
    border:2px solid var(--dark)!important;
    border-top:none!important;
    border-radius:0 0 12px 12px!important;
}
[data-testid="stExpanderDetails"] [data-testid="stMarkdownContainer"],
[data-testid="stExpanderDetails"] p,
[data-testid="stExpanderDetails"] span,
[data-testid="stExpanderDetails"] div{color:var(--dark)!important;}

/* ── METRICS ── */
[data-testid="stMetric"]{background:linear-gradient(170deg,#fff 0%,var(--surface) 100%)!important;border:2.5px solid var(--dark)!important;border-radius:14px!important;box-shadow:0 12px 24px rgba(18,13,42,.14),4px 4px 0 var(--dark)!important;padding:1rem!important;transition:transform .12s,box-shadow .12s!important;}
[data-testid="stMetric"]:hover{transform:translate(-2px,-2px)!important;box-shadow:0 16px 30px rgba(18,13,42,.2),6px 6px 0 var(--dark)!important;}
[data-testid="stMetricValue"]{font-family:'Fredoka One',cursive!important;color:var(--purple)!important;font-size:2rem!important;}
[data-testid="stMetricLabel"]{color:var(--dark)!important;font-weight:800!important;}

/* ── PROGRESS ── */
.stProgress>div>div>div{background:var(--purple)!important;border-radius:50px!important;}
.stProgress>div>div{background:#E0D5FF!important;border:2px solid var(--dark)!important;border-radius:50px!important;height:10px!important;}

/* ── DOWNLOAD BUTTON ── */
[data-testid="stDownloadButton"]>button{background:var(--mint)!important;color:var(--dark)!important;border:2.5px solid var(--dark)!important;border-radius:12px!important;box-shadow:4px 4px 0 var(--dark)!important;font-weight:800!important;font-family:'Nunito',sans-serif!important;}
[data-testid="stDownloadButton"]>button:hover{transform:translate(-2px,-2px)!important;box-shadow:6px 6px 0 var(--dark)!important;}

/* ── FOOTER ── */
.custom-footer{background:linear-gradient(165deg,#241A4D 0%,var(--dark) 100%)!important;border:3px solid var(--dark)!important;border-radius:20px!important;box-shadow:0 16px 30px rgba(18,13,42,.22),6px 6px 0 rgba(28,20,51,.2)!important;padding:2rem!important;text-align:center!important;margin-top:2rem!important;}
.custom-footer p{color:rgba(255,255,255,.7)!important;font-weight:600!important;margin:.3rem 0!important;}
.custom-footer strong{color:var(--yellow)!important;font-family:'Fredoka One',cursive!important;}

/* ── HEADINGS ── */
h1,h2,h3,.block-container h1,.block-container h2,.block-container h3{font-family:'Fredoka One',cursive!important;color:var(--dark)!important;}
.block-container h3{font-size:1.4rem!important;border-bottom:2px solid rgba(28,20,51,.12);padding-bottom:.3rem;margin-bottom:1rem!important;}

/* ── MISC ── */
hr{border-color:rgba(28,20,51,.12)!important;border-width:2px!important;}
.stCaption p,caption,.stCaption span{color:#666!important;font-weight:600!important;}
.stSpinner>div{border-top-color:var(--purple)!important;}

/* ── ANIMATION ── */
@keyframes nbFadeIn{from{opacity:0;transform:translateY(16px);}to{opacity:1;transform:translateY(0);}}
.fade-in{animation:nbFadeIn .45s cubic-bezier(.34,1.56,.64,1) both;}
</style>
"""

CURSOR_HTML = """
<script>
(() => {
    if (window.__dynamicCursorReady) return;
    window.__dynamicCursorReady = true;

    const hasFinePointer = window.matchMedia('(pointer:fine)').matches;
    if (!hasFinePointer) return;

    const dot = document.createElement('div');
    dot.className = 'cursor-dot';
    const ring = document.createElement('div');
    ring.className = 'cursor-ring';
    document.body.appendChild(ring);
    document.body.appendChild(dot);

    let mouseX = window.innerWidth / 2;
    let mouseY = window.innerHeight / 2;
    let ringX = mouseX;
    let ringY = mouseY;

    const follow = () => {
        ringX += (mouseX - ringX) * 0.16;
        ringY += (mouseY - ringY) * 0.16;
        dot.style.left = mouseX + 'px';
        dot.style.top = mouseY + 'px';
        ring.style.left = ringX + 'px';
        ring.style.top = ringY + 'px';
        requestAnimationFrame(follow);
    };
    follow();

    window.addEventListener('mousemove', (event) => {
        mouseX = event.clientX;
        mouseY = event.clientY;
    }, { passive: true });

    const interactiveSelector = 'a, button, [role="button"], input, textarea, select, summary, label, [data-baseweb="tab"]';
    document.addEventListener('mouseover', (event) => {
        if (event.target.closest(interactiveSelector)) {
            ring.classList.add('active');
        }
    });

    document.addEventListener('mouseout', (event) => {
        if (event.target.closest(interactiveSelector)) {
            ring.classList.remove('active');
        }
    });

    window.addEventListener('mousedown', () => {
        dot.classList.add('click');
        ring.classList.add('active');
    });

    window.addEventListener('mouseup', () => {
        dot.classList.remove('click');
    });

    document.addEventListener('visibilitychange', () => {
        const hidden = document.hidden;
        dot.style.opacity = hidden ? '0' : '1';
        ring.style.opacity = hidden ? '0' : '1';
    });
})();
</script>
"""

# =============================================
# NOT-AUTH: LANDING / AUTH PAGES
# =============================================
if not is_authenticated():
    if "show_auth" not in st.session_state:
        st.session_state.show_auth = False
    if "auth_mode" not in st.session_state:
        st.session_state.auth_mode = "login"

    params = st.query_params
    if params.get("action") == "signup":
        st.session_state.show_auth = True
        st.session_state.auth_mode = "register"
        st.query_params.clear()
    elif params.get("action") == "login":
        st.session_state.show_auth = True
        st.session_state.auth_mode = "login"
        st.query_params.clear()
    elif params.get("action") == "back":
        st.session_state.show_auth = False
        st.query_params.clear()

    if not st.session_state.show_auth:
        # Login button callback
        def goto_login():
            st.session_state.show_auth = True
            st.session_state.auth_mode = "login"
        
        # Signup button callback
        def goto_signup():
            st.session_state.show_auth = True
            st.session_state.auth_mode = "register"
        
        render_html(LP_CSS + """
        <nav class="lp-nav">
            <a class="nav-logo" href="#">Study<span class="dot">Hub</span></a>
            <ul class="nav-links-row">
                <li><a href="#features">Features</a></li>
                <li><a href="#how">How it works</a></li>
                <li><a href="#reviews">Reviews</a></li>
            </ul>
            <div class="nav-right-btns" id="nav-buttons">
                <a href="?action=login" class="lp-btn lp-btn-sm lp-btn-ghost">Sign in</a>
                <a href="?action=signup" class="lp-btn lp-btn-sm lp-btn-dark">Get Started</a>
            </div>
        </nav>
        <section class="hero" id="home">
            <span class="shape" style="top:20%;left:6%;font-size:2.4rem;">✏️</span>
            <span class="shape" style="top:22%;right:8%;font-size:2.6rem;animation-delay:-1.5s;">🎓</span>
            <span class="shape" style="bottom:24%;left:9%;font-size:2.2rem;animation-delay:-2.8s;">💡</span>
            <span class="shape" style="bottom:20%;right:7%;font-size:2.8rem;animation-delay:-.9s;">⭐</span>
            <span class="shape" style="top:14%;left:40%;font-size:1.7rem;animation-delay:-3.2s;">🔥</span>
            <div class="hero-chip">✨ AI-Powered · Free to Start</div>
            <h1 class="hero-title">Turn Any Lecture Into<br><span class="hl-purple">Exam-Ready</span> <span class="hl-coral">Notes</span></h1>
            <p class="hero-sub">Upload audio, video, or PDF and get comprehensive summaries, smart flashcards, and exam insights — generated in seconds.</p>
            <div class="hero-cta-row">
                <a href="?action=signup" class="lp-btn lp-btn-md lp-btn-dark">🚀 Get Started Free</a>
                <a href="?action=login" class="lp-btn lp-btn-md lp-btn-white">Log in →</a>
            </div>
        </section>
        <div class="stats-strip">
            <div class="stat-box"><span class="stat-num">50K+</span><div class="stat-label">Study Sessions</div></div>
            <div class="stat-box"><span class="stat-num">2M+</span><div class="stat-label">Flashcards Created</div></div>
            <div class="stat-box"><span class="stat-num">98%</span><div class="stat-label">Student Satisfaction</div></div>
            <div class="stat-box"><span class="stat-num">12+</span><div class="stat-label">File Formats</div></div>
            <div class="stat-box"><span class="stat-num">4.9★</span><div class="stat-label">Average Rating</div></div>
        </div>
        <section class="section features-bg" id="features">
          <div class="section-inner">
            <span class="section-eyebrow">⚡ Features</span>
            <h2 class="section-title">Everything you need to ace your exams</h2>
            <p class="section-sub">From raw lecture recordings to structured study materials — all powered by AI.</p>
            <div class="features-grid">
              <div class="feat-card c1"><span class="feat-icon">🎤</span><h3>Audio &amp; Video Transcription</h3><p>Upload any lecture recording — MP3, MP4, WAV, MOV. Our AI transcribes and extracts the core content instantly.</p><span class="feat-tag">Whisper AI</span></div>
              <div class="feat-card c2"><span class="feat-icon">📄</span><h3>PDF Text Extraction</h3><p>Drop in textbook chapters, slides, or research papers. We parse and structure everything automatically.</p><span class="feat-tag">Smart Parsing</span></div>
              <div class="feat-card c3"><span class="feat-icon">🧠</span><h3>AI-Generated Summaries</h3><p>Get concise, exam-focused summaries with core concepts, key mechanisms, formulas, and processes highlighted.</p><span class="feat-tag">GPT-4 Powered</span></div>
              <div class="feat-card c4"><span class="feat-icon">🃏</span><h3>Smart Flashcard Decks</h3><p>Auto-generated Q&amp;A flashcards with spaced repetition tracking. Mark as Mastered or Still Learning.</p><span class="feat-tag">Active Recall</span></div>
              <div class="feat-card c5"><span class="feat-icon">🎯</span><h3>Exam Insights &amp; FAQ</h3><p>AI pinpoints the most likely exam topics, real-world applications, and common mistakes to avoid.</p><span class="feat-tag">Exam-Ready</span></div>
              <div class="feat-card c6"><span class="feat-icon">💾</span><h3>Export in Any Format</h3><p>Download your study notes as PDF, Markdown, or Word. Notes are saved across all your sessions.</p><span class="feat-tag">PDF · MD · DOCX</span></div>
            </div>
          </div>
        </section>
        <section class="section how-bg" id="how">
          <div class="section-inner">
            <span class="section-eyebrow">📖 How it works</span>
            <h2 class="section-title">Three steps to better grades</h2>
            <p class="section-sub" style="color:rgba(255,255,255,.65);">From upload to exam-ready in under 60 seconds.</p>
            <div class="steps-row">
              <div class="step-card"><div class="step-num-box">1</div><h4>Upload Your Content</h4><p>Drop in a lecture recording, PDF textbook, or record live with your microphone.</p></div>
              <div class="step-card"><div class="step-num-box">2</div><h4>AI Does the Work</h4><p>Our models transcribe, analyse, and extract concepts, formulas, and insights automatically.</p></div>
              <div class="step-card"><div class="step-num-box">3</div><h4>Study Smarter</h4><p>Review your summary, drill flashcards, and download polished notes ready for exam prep.</p></div>
              <div class="step-card"><div class="step-num-box">4</div><h4>Track Progress</h4><p>See study streaks, mastery progress, and analytics across all your sessions over time.</p></div>
            </div>
          </div>
        </section>
        <section class="section testi-bg" id="reviews">
          <div class="section-inner">
            <span class="section-eyebrow">💬 Reviews</span>
            <h2 class="section-title">Students are loving it</h2>
            <p class="section-sub">Real results from real students all around the world.</p>
            <div class="testi-grid">
              <div class="testi-card"><div class="testi-stars">★★★★★</div><p class="testi-text">"I went from spending 4 hours making notes to under 10 minutes. The flashcards are scary accurate for what shows up on exams!"</p><div class="testi-author"><div class="testi-av" style="background:#6C3CE1;">AK</div><div><div class="testi-name">Aisha K.</div><div class="testi-role">Medical Student · UCL</div></div></div></div>
              <div class="testi-card"><div class="testi-stars">★★★★★</div><p class="testi-text">"Uploaded a 120-page textbook chapter and got a detailed summary with flashcards in seconds. This is genuinely game-changing."</p><div class="testi-author"><div class="testi-av" style="background:#FF6B6B;">MR</div><div><div class="testi-name">Marcus R.</div><div class="testi-role">CS Major · MIT</div></div></div></div>
              <div class="testi-card"><div class="testi-stars">★★★★★</div><p class="testi-text">"My GPA went from 2.8 to 3.6 in one semester. The spaced repetition tracking keeps me consistent without even thinking about it."</p><div class="testi-author"><div class="testi-av" style="background:#00C9A7;">JL</div><div><div class="testi-name">Julia L.</div><div class="testi-role">Law Student · Edinburgh</div></div></div></div>
            </div>
          </div>
        </section>
        <section class="cta-bg">
            <h2 class="section-title" style="font-family:'Fredoka One',cursive;">Ready to study smarter? 🚀</h2>
            <p class="cta-sub">Join thousands of students already using AI to ace their exams. Free forever to get started.</p>
            <div class="cta-btn-row">
                <a href="?action=signup" class="lp-btn lp-btn-lg lp-btn-dark">🎓 Create Free Account</a>
                <a href="?action=login" class="lp-btn lp-btn-lg lp-btn-white">Sign in →</a>
            </div>
        </section>
        <footer class="lp-footer">
            <div class="footer-logo">Study Hub</div>
            <p>© 2026 Study Hub · Built with ♡ for students everywhere · v4.0</p>
            <div class="footer-links"><a href="#">Privacy</a><a href="#">Terms</a><a href="#">Contact</a></div>
        </footer>
        """)
        
        # Add invisible callback buttons for faster responsiveness
        col1, col2, col3 = st.columns([3, 1, 1])
        with col1:
            pass
        with col2:
            if st.button("Login (invisible)", key="lp_login_btn", use_container_width=True, on_click=goto_login):
                pass
        with col3:
            if st.button("Signup (invisible)", key="lp_signup_btn", use_container_width=True, on_click=goto_signup):
                pass
        
        # Hide those buttons with CSS
        st.markdown("""
            <style>
                button[key="lp_login_btn"], button[key="lp_signup_btn"],
                [data-testid="stButton"] button[aria-label*="invisible"] {
                    display: none !important;
                }
            </style>
        """, unsafe_allow_html=True)
        
        st.stop()

    else:
        is_register = st.session_state.auth_mode == "register"
        page_title = "Create your account" if is_register else "Welcome back!"
        page_sub = "Join thousands of students acing their exams." if is_register else "Sign in to continue your study journey."
        hero_emoji = "🎓" if is_register else "👋"
        switch_href = "?action=login" if is_register else "?action=signup"
        switch_txt = "Sign in →" if is_register else "Create account →"
        switch_pre = "Already have an account?" if is_register else "New here?"

        if st.query_params.get("action") == "back":
            st.session_state.show_auth = False
            st.query_params.clear()
            st.rerun()

        render_html(f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Fredoka+One&family=Nunito:wght@400;500;600;700;800;900&display=swap');
        :root{{--yellow:#FFD60A;--yellow2:#FFEB5B;--purple:#6C3CE1;--coral:#FF6B6B;--cream:#FFFBF0;--dark:#1C1433;}}
        header[data-testid="stHeader"],footer,#MainMenu,section[data-testid="stSidebar"]{{display:none!important;}}
        *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0;}}
        html,body,.stApp{{background:var(--cream)!important;font-family:'Nunito',sans-serif;color:var(--dark);overflow-x:hidden;}}
        .block-container{{margin-left:42%!important;max-width:58%!important;padding:calc(68px + 1.5rem) 3.5rem 3rem!important;background:var(--cream)!important;min-height:100vh;}}
        .block-container>div{{max-width:{'500px' if is_register else '520px'};margin-left:auto;margin-right:auto;}}
        .lp-nav{{position:fixed;top:0;left:0;right:0;z-index:2000;display:flex;align-items:center;justify-content:space-between;padding:0 3.5rem;height:68px;background:#fff;border-bottom:3px solid var(--dark);box-shadow:0 4px 0 var(--dark);}}
        .nav-logo{{display:flex;align-items:center;gap:.6rem;font-family:'Fredoka One',cursive;font-size:1.55rem;color:var(--dark);text-decoration:none;}}
        .nav-logo .dot{{color:var(--purple);}}
        .logo-icon{{background:var(--yellow);width:38px;height:38px;border-radius:10px;border:2.5px solid var(--dark);display:flex;align-items:center;justify-content:center;font-size:1.2rem;box-shadow:3px 3px 0 var(--dark);}}
        .auth-left{{position:fixed;top:68px;left:0;width:42%;height:calc(100vh - 68px);background:var(--purple);border-right:3px solid var(--dark);display:flex;flex-direction:column;align-items:center;justify-content:center;padding:3rem 2.5rem;overflow:hidden;z-index:100;}}
        .auth-left::before{{content:'';position:absolute;top:-80px;right:-80px;width:280px;height:280px;border-radius:50%;background:var(--yellow);opacity:.13;pointer-events:none;}}
        .auth-left::after{{content:'';position:absolute;bottom:-60px;left:-60px;width:220px;height:220px;border-radius:50%;background:var(--coral);opacity:.18;pointer-events:none;}}
        .auth-floater{{position:absolute;pointer-events:none;animation:authFloat 4s ease-in-out infinite;}}
        .auth-chip{{display:inline-flex;align-items:center;gap:.4rem;background:var(--yellow);color:var(--dark);font-weight:800;font-size:.75rem;letter-spacing:1px;text-transform:uppercase;padding:.38rem 1rem;border-radius:50px;border:2px solid var(--dark);box-shadow:3px 3px 0 var(--dark);margin-bottom:1.4rem;position:relative;z-index:1;}}
        .auth-big-emoji{{font-size:4.5rem;margin-bottom:1.2rem;animation:authFloat 3.5s ease-in-out infinite;filter:drop-shadow(0 8px 20px rgba(0,0,0,.3));position:relative;z-index:1;}}
        .auth-left h2{{font-family:'Fredoka One',cursive;font-size:clamp(1.5rem,2.2vw,2.2rem);color:#fff;text-align:center;line-height:1.15;margin-bottom:.6rem;position:relative;z-index:1;}}
        .auth-left-sub{{font-size:.93rem;font-weight:600;color:rgba(255,255,255,.7);text-align:center;line-height:1.65;max-width:300px;margin-bottom:1.8rem;position:relative;z-index:1;}}
        .auth-benefits{{display:flex;flex-direction:column;gap:.65rem;width:100%;max-width:300px;position:relative;z-index:1;}}
        .auth-benefit-item{{display:flex;align-items:center;gap:.7rem;background:rgba(255,255,255,.1);border:1.5px solid rgba(255,255,255,.2);border-radius:12px;padding:.65rem .9rem;transition:background .2s;}}
        .auth-benefit-item:hover{{background:rgba(255,255,255,.18);}}
        .auth-benefit-icon{{font-size:1.2rem;flex-shrink:0;}}
        .auth-benefit-text{{font-size:.84rem;font-weight:700;color:rgba(255,255,255,.88);}}
        .auth-back-btn{{font-family:'Nunito',sans-serif;font-weight:800;font-size:.83rem;background:transparent;color:var(--dark);border:2.5px solid var(--dark);border-radius:10px;padding:.42rem .9rem;box-shadow:3px 3px 0 var(--dark);transition:transform .12s,box-shadow .12s;text-decoration:none;display:inline-flex;align-items:center;gap:.35rem;}}
        .auth-back-btn:hover{{transform:translate(-2px,-2px);box-shadow:5px 5px 0 var(--dark);}}
        .auth-form-heading{{font-family:'Fredoka One',cursive;font-size:2rem;color:var(--dark);line-height:1.1;margin:.2rem 0 .4rem;}}
        .auth-form-sub{{font-size:.95rem;font-weight:600;color:#666;line-height:1.55;margin-bottom:1.2rem;}}
        .auth-divider{{display:flex;align-items:center;gap:.75rem;margin-bottom:1rem;}}
        .auth-divider hr{{flex:1;border:none;border-top:2px solid rgba(28,20,51,.15);}}
        .auth-divider span{{font-size:.72rem;font-weight:800;color:#bbb;text-transform:uppercase;letter-spacing:1px;}}
        .auth-switch-row{{text-align:center;margin-top:1.2rem;font-size:.9rem;font-weight:700;color:#888;}}
        .auth-switch-row a{{color:var(--purple);font-weight:900;text-decoration:none;border-bottom:2px solid var(--purple);padding-bottom:1px;}}
        .stTextInput input{{font-family:'Nunito',sans-serif!important;font-weight:700!important;border:2.5px solid var(--dark)!important;border-radius:12px!important;box-shadow:4px 4px 0 var(--dark)!important;background:#fff!important;color:var(--dark)!important;transition:box-shadow .14s,transform .14s!important;}}
        .stTextInput input:focus{{transform:translate(-2px,-2px)!important;box-shadow:6px 6px 0 var(--dark)!important;outline:none!important;}}
        .stTextInput label{{font-family:'Nunito',sans-serif!important;font-weight:800!important;font-size:.8rem!important;text-transform:uppercase!important;letter-spacing:.6px!important;color:var(--dark)!important;}}
        .stTextInput [data-testid="InputInstructions"],
        .stTextInput [data-testid="InputInstructions"] *{{display:none!important;visibility:hidden!important;height:0!important;max-height:0!important;margin:0!important;padding:0!important;}}
        .stButton>button{{font-family:'Nunito',sans-serif!important;font-weight:900!important;background:var(--dark)!important;color:var(--yellow)!important;border:3px solid var(--dark)!important;border-radius:14px!important;box-shadow:5px 5px 0 rgba(28,20,51,.2)!important;font-size:1rem!important;padding:.65rem 1.5rem!important;width:100%!important;transition:transform .12s,box-shadow .12s!important;}}
        .stButton>button:hover{{transform:translate(-2px,-2px)!important;box-shadow:7px 7px 0 rgba(28,20,51,.2)!important;}}
        .stButton>button:active{{transform:translate(2px,2px)!important;box-shadow:2px 2px 0 rgba(28,20,51,.2)!important;}}
        @keyframes authFloat{{0%,100%{{transform:translateY(0) rotate(0deg);}}50%{{transform:translateY(-14px) rotate(6deg);}}}}
        </style>
        <nav class="lp-nav">
            <a class="nav-logo" href="?action=back" target="_self">Study<span class="dot">Hub</span></a>
            <div style="font-size:.87rem;font-weight:700;color:#888;">{switch_pre}&nbsp;<a href="{switch_href}" style="color:var(--purple);font-weight:900;text-decoration:none;border-bottom:2px solid var(--purple);">{switch_txt}</a></div>
        </nav>
        <div class="auth-left">
            <span class="auth-floater" style="top:10%;left:7%;font-size:2rem;">✏️</span>
            <span class="auth-floater" style="top:18%;right:8%;font-size:1.9rem;animation-delay:-1.5s;">⭐</span>
            <span class="auth-floater" style="bottom:20%;left:8%;font-size:1.7rem;animation-delay:-2.7s;">💡</span>
            <span class="auth-floater" style="bottom:12%;right:7%;font-size:2.1rem;animation-delay:-.9s;">🔥</span>
            <div class="auth-chip">✨ Free to Start · No Card Needed</div>
            <div class="auth-big-emoji">{hero_emoji}</div>
            <h2>{page_title}</h2>
            <p class="auth-left-sub">{page_sub}</p>
            <div class="auth-benefits">
                <div class="auth-benefit-item"><span class="auth-benefit-icon">🎤</span><span class="auth-benefit-text">Audio &amp; Video Transcription</span></div>
                <div class="auth-benefit-item"><span class="auth-benefit-icon">🧠</span><span class="auth-benefit-text">AI-Generated Exam Summaries</span></div>
                <div class="auth-benefit-item"><span class="auth-benefit-icon">🃏</span><span class="auth-benefit-text">Smart Spaced-Repetition Flashcards</span></div>
                <div class="auth-benefit-item"><span class="auth-benefit-icon">💾</span><span class="auth-benefit-text">Export as PDF, Markdown or Word</span></div>
                <div class="auth-benefit-item"><span class="auth-benefit-icon">📊</span><span class="auth-benefit-text">Progress Tracking &amp; Analytics</span></div>
            </div>
        </div>
        """)

        st.markdown(f"""
        <a href="?action=back" target="_self" class="auth-back-btn">← Back to Home</a>
        <h1 class="auth-form-heading">{page_title}</h1>
        <p class="auth-form-sub">{page_sub}</p>
        <div class="auth-divider"><hr><span>enter your details below</span><hr></div>
        """, unsafe_allow_html=True)

        show_auth_page(embedded=True)

        if is_register:
            st.markdown('<p class="auth-switch-row">Already have an account? <a href="?action=login">Sign in →</a></p>', unsafe_allow_html=True)
        else:
            st.markdown('<p class="auth-switch-row">New here? <a href="?action=signup">Create account →</a></p>', unsafe_allow_html=True)

        st.stop()


# =============================================
# MAIN APP — authenticated users
# =============================================
user = get_current_user()

# Inject 3D dynamic theme
st.markdown(APP_CSS, unsafe_allow_html=True)

logo_path = "silvy_logo.png"
if os.path.exists(logo_path):
    with open(logo_path, "rb") as image_file:
        encoded = base64.b64encode(image_file.read()).decode()
        st.markdown(f"<div style='text-align:center;margin-top:-2rem;margin-bottom:1rem;'><img src='data:image/png;base64,{encoded}' style='height:80px;'/></div>", unsafe_allow_html=True)

if is_authenticated() and st.session_state.get("session_token"):
    st.markdown(f"<script>localStorage.setItem('auth_token','{st.session_state.session_token}');</script>", unsafe_allow_html=True)

if "session_token" not in st.session_state: st.session_state.session_token = None
if "processing" not in st.session_state: st.session_state.processing = False
if "mic_job_running" not in st.session_state: st.session_state.mic_job_running = False
if "mic_job_result" not in st.session_state: st.session_state.mic_job_result = None
if "mic_job_thread" not in st.session_state: st.session_state.mic_job_thread = None
if "mic_stop_event" not in st.session_state: st.session_state.mic_stop_event = None
if "mic_result_queue" not in st.session_state: st.session_state.mic_result_queue = None
if "history" not in st.session_state: st.session_state.history = get_user_notes(user["id"])
if "current_result" not in st.session_state: st.session_state.current_result = None
if "personal_notes" not in st.session_state: st.session_state.personal_notes = get_personal_notes(user["id"])
if "fc_index" not in st.session_state: st.session_state.fc_index = 0
if "fc_status" not in st.session_state: st.session_state.fc_status = {}
if "mastered_cards" not in st.session_state: st.session_state.mastered_cards = 0
if "input_method" not in st.session_state: st.session_state.input_method = "file"
if "active_section" not in st.session_state: st.session_state.active_section = "summary"

st.markdown("""
<div class="main-header fade-in">
    <span style="position:absolute;top:1rem;left:1.5rem;font-size:1.6rem;opacity:.2;pointer-events:none;">✏️</span>
    <span style="position:absolute;top:1rem;right:1.5rem;font-size:1.6rem;opacity:.2;pointer-events:none;">⭐</span>
    <div class="main-title">Exam Study Hub Generator</div>
    <div class="subtitle">Transform lectures &amp; PDFs into comprehensive study materials for exam success</div>
    <div style="margin-top:1rem;"><span class="glow-badge">✨ AI-Powered for Students</span></div>
</div>
""", unsafe_allow_html=True)

with st.sidebar:
    user_initials = "".join([w[0].upper() for w in (user.get("name") or user.get("email", "")).split()[:2]])
    display_name = user.get("name") or user.get("email", "User")
    st.markdown(f"""
    <div class="profile-card">
        <div class="profile-avatar">{user_initials}</div>
        <div class="profile-info">
            <p class="profile-name">{display_name}</p>
            <p class="profile-email">{user.get("email", "")}</p>
        </div>
        <span class="profile-status">● Online</span>
    </div>
    """, unsafe_allow_html=True)

    if st.button("Logout", key="logout_btn", use_container_width=True):
        logout()
        st.rerun()

    st.markdown("---")
    user_stats = get_user_stats(user["id"])
    days_active = 0
    if user_stats.get("last_activity"):
        try:
            last_date = datetime.fromisoformat(user_stats["last_activity"]).date()
            today = datetime.now().date()
            if last_date == today or last_date == today - timedelta(days=1):
                days_active = max(1, user_stats.get("total_notes", 0))
        except: pass

    st.markdown(f"""
    <div style="background:var(--yellow2);border:2.5px solid var(--dark);border-radius:14px;
                box-shadow:4px 4px 0 var(--dark);padding:1rem;margin-bottom:1rem;">
        <div style="display:flex;align-items:center;gap:.8rem;">
            <div style="font-size:2rem;">🔥</div>
            <div>
                <p style="margin:0;font-size:.75rem;color:#888;text-transform:uppercase;letter-spacing:.5px;font-weight:800;">Study Streak</p>
                <p style="margin:0;font-size:1.4rem;font-weight:900;color:var(--dark);font-family:'Fredoka One',cursive;">{days_active} Day{'s' if days_active!=1 else ''}</p>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    tips = [
        "📌 Use spaced repetition: Review after 1 day, 3 days, then 7 days.",
        "🎯 Break sessions into 25-min intervals with 5-min breaks (Pomodoro).",
        "✍️ Writing notes by hand improves retention by 34%!",
        "🧠 Teaching concepts to others is the best way to master them.",
        "⏰ Study difficult topics in the morning when your brain is fresh.",
        "🎵 Classical or lo-fi music can boost focus without distracting.",
        "💧 Stay hydrated! Dehydration reduces cognitive performance by 12%.",
        "🌙 Quality sleep consolidates memories — aim for 7-8 hours.",
    ]
    with st.expander("💡 Today's Study Tip", expanded=False):
        st.markdown(f"<p style='font-size:.9rem;line-height:1.6;color:var(--dark);font-weight:600;'>{tips[datetime.now().day % len(tips)]}</p>", unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("<p style='margin:0;font-size:1.12rem;font-weight:900;color:var(--dark);'>📖 Active Session</p>", unsafe_allow_html=True)
    if st.session_state.current_result and "error" not in st.session_state.current_result:
        r = st.session_state.current_result
        sc = len(r.get("core_concepts",{}).get("definitions",[])) + len(r.get("core_concepts",{}).get("mechanisms",[]))
        fc = len(r.get("active_recall",{}).get("qa_cards",[]))
        st.markdown(f"""
        <div class="content-nav">
            <div class="content-nav-item"><span>📄 Summary</span><span class="nav-badge">{sc}</span></div>
            <div class="content-nav-item"><span>🃏 Flashcards</span><span class="nav-badge">{fc}</span></div>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.caption("No active study session")

    st.markdown("---")
    st.markdown("**📊 Stats & Activity**")
    c1, c2 = st.columns(2)
    with c1: st.metric("Total Notes", user_stats.get("total_notes", 0))
    with c2:
        tfc = sum(len(i["result"].get("active_recall",{}).get("qa_cards",[])) for i in st.session_state.history)
        st.metric("Flashcards", tfc)

    if st.session_state.history:
        st.markdown("<p style='font-size:.75rem;color:#aaa;margin-top:.5rem;margin-bottom:.3rem;font-weight:800;text-transform:uppercase;letter-spacing:.5px;'>RECENT ACTIVITY</p>", unsafe_allow_html=True)
        for item in st.session_state.history[:3]:
            it = item.get("input_type","unknown").title()
            try:
                ta = (datetime.now() - datetime.fromisoformat(item.get("timestamp",""))).total_seconds()
                ts = f"{int(ta//60)}m ago" if ta<3600 else f"{int(ta//3600)}h ago" if ta<86400 else f"{int(ta//86400)}d ago"
            except: ts = item.get("timestamp","")
            st.markdown(f"""
            <div style="display:flex;align-items:center;gap:.5rem;padding:.4rem 0;border-bottom:2px solid rgba(28,20,51,.07);">
                <span>{"📄" if it=="Pdf" else "🎤" if it=="Mic" else "📁"}</span>
                <span style="flex:1;font-size:.8rem;color:var(--dark);font-weight:700;">{it}</span>
                <span style="font-size:.7rem;color:#aaa;font-weight:600;">{ts}</span>
            </div>""", unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("<p style='margin:0;font-size:1.12rem;font-weight:900;color:var(--dark);'>📈 Session Progress</p>", unsafe_allow_html=True)
    if st.session_state.current_result and "error" not in st.session_state.current_result:
        fct = len(st.session_state.current_result.get("active_recall",{}).get("qa_cards",[]))
        ms = st.session_state.get("mastered_cards", 0)
        pp = int(ms/fct*100) if fct>0 else 0
        st.markdown(f"""<div style="margin:.8rem 0;"><div style="display:flex;justify-content:space-between;margin-bottom:.3rem;"><span style="font-size:.75rem;color:#888;font-weight:700;">Flashcards Mastered</span><span style="font-size:.75rem;font-weight:900;color:var(--mint);">{ms}/{fct}</span></div></div>""", unsafe_allow_html=True)
        st.progress(min(pp/100, 1.0))
        if pp==100: st.success("🎉 Session Complete!")
        elif pp>=50: st.info("🚀 You are halfway there!")
    else:
        st.caption("Start a session to track progress")


tab1, tab2, tab3 = st.tabs(["📚 Generate Notes", "📖 Study History", "📊 Analytics"])

with tab1:
    st.markdown("### 💾 Export Format")
    export_format = st.radio("Select Output Format:", ["PDF", "Markdown", "Word"], horizontal=True)
    summary_length = st.select_slider(
        "Summary Length",
        options=["Brief", "Medium", "Detailed"],
        value="Medium"
    )

    st.markdown("### ✉ File Upload")
    uploaded_file = st.file_uploader("Upload Audio, Video, or PDF", type=["wav","mp3","m4a","mp4","avi","mov","mpeg","pdf"])
    if uploaded_file:
        st.info(f"File: {uploaded_file.name}")
        if uploaded_file.type == "application/pdf": 
            st.success("✓ PDF file selected")
        elif uploaded_file.type.startswith("audio"): 
            with st.expander("🔊 Play Audio Preview", expanded=False):
                st.audio(uploaded_file)
        elif uploaded_file.type.startswith("video"): 
            with st.expander("🎬 Play Video Preview", expanded=False):
                st.video(uploaded_file)
        
        st.markdown("")
        if st.button("🚀 Summarize & Generate Notes", use_container_width=True, type="primary", key="summarize_btn"):
            st.session_state.processing = True
            
            # Save file with absolute path
            import tempfile
            temp_dir = tempfile.gettempdir()
            file_path = os.path.join(temp_dir, f"temp_{uploaded_file.name}")
            
            with open(file_path, "wb") as f:
                f.write(uploaded_file.getvalue())
            
            # Ensure file is fully written
            time.sleep(0.5)
            
            # Verify file was written successfully
            if not os.path.exists(file_path):
                st.error(f"❌ Failed to save file: {file_path}")
                st.session_state.processing = False
            elif os.path.getsize(file_path) == 0:
                st.error(f"❌ File is empty, upload failed")
                st.session_state.processing = False
            else:
                try:
                    with st.spinner("Processing file..."):
                        if uploaded_file.type == "application/pdf":
                            try:
                                result = process_input(
                                    source_type="pdf",
                                    pdf_text=process_pdf(file_path),
                                    export_format=export_format,
                                    summary_length=summary_length
                                )
                            except RuntimeError as e:
                                st.error(f"⚠️ PDF error: {e}"); result = {"error": str(e)}
                        else:
                            result = process_input(
                                source_type="file",
                                file_path=file_path,
                                export_format=export_format,
                                summary_length=summary_length
                            )
                        st.session_state.current_result = result
                except Exception as e:
                    st.error(f"❌ Error: {e}"); result = {"error": str(e)}
                    st.session_state.current_result = result
                finally:
                    st.session_state.processing = False
                    # Clean up after a delay
                    time.sleep(0.5)
                    if os.path.exists(file_path): 
                        try:
                            os.remove(file_path)
                        except:
                            pass


if st.session_state.current_result:
    result = st.session_state.current_result
    if "error" in result:
        st.error(f"✘ Error: {result['error']}")
    else:
        st.markdown("""<div class="results-header fade-in">
            <div class="results-title">✅ Study Notes Generated Successfully!</div>
            <div style="color:var(--dark);font-weight:600;opacity:.7;margin-top:.3rem;">Your comprehensive study materials are ready</div>
        </div>""", unsafe_allow_html=True)
        search_term = st.text_input("🔍 Search in notes:", placeholder="Enter keyword to search...")

        sc = len(result.get("core_concepts",{}).get("definitions",[])) + len(result.get("core_concepts",{}).get("mechanisms",[]))
        fc = len(result.get("active_recall",{}).get("qa_cards",[]))

        nav_items = {
            "summary":    f"📄 Summary ({sc})",
            "flashcards": f"🃏 Flashcards ({fc})",
        }
        if st.session_state.active_section not in nav_items:
            st.session_state.active_section = "summary"

        _, content_col = st.columns([0.01, 0.99])
        with content_col:
            st.session_state.active_section = st.radio(
                "View", options=list(nav_items.keys()),
                format_func=lambda k: nav_items[k],
                horizontal=True, key="active_section_selector",
                label_visibility="collapsed")
            active = st.session_state.active_section

            if active == "summary":
                snap = result.get("concept_snapshot",{})
                structured_summary = result.get("structured_summary", "")
                st.markdown("""<div class="summary-card"><div class="summary-card-header"><h2 class="summary-card-title">Smart Summary</h2><span class="summary-meta">Structured, exam-focused notes</span></div></div>""", unsafe_allow_html=True)
                wt = snap.get("what","Summary not available.")
                wy = snap.get("why","")
                where = snap.get("where","")
                if search_term:
                    wt = wt.replace(search_term,f"**{search_term}**") if search_term.lower() in wt.lower() else wt
                    wy = wy.replace(search_term,f"**{search_term}**") if search_term.lower() in wy.lower() else wy
                    where = where.replace(search_term,f"**{search_term}**") if search_term and search_term.lower() in where.lower() else where

                if structured_summary.strip():
                    if search_term and search_term.lower() in structured_summary.lower():
                        structured_summary = structured_summary.replace(search_term, f"**{search_term}**")
                    st.markdown("""<div class="glass-container quick-summary-body">""", unsafe_allow_html=True)
                    st.markdown(structured_summary)
                    st.markdown("""</div>""", unsafe_allow_html=True)
                else:
                    st.markdown(f"""<div class="glass-container quick-summary-body">
                        <div style="margin-bottom:1.5rem;">
                            <h3 style="color:#FF1493;margin-bottom:0.5rem;font-size:1.1rem;">📌 What is this?</h3>
                            <p style="line-height:2;color:var(--dark);font-size:1rem;margin:0;">{wt}</p>
                        </div>
                        {f'<div style="margin-bottom:1.5rem;"><h3 style="color:#FF1493;margin-bottom:0.5rem;font-size:1.1rem;">❓ Why does it matter?</h3><p style="line-height:2;color:var(--dark2);font-size:0.95rem;margin:0;">{wy}</p></div>' if wy else ''}
                        {f'<div><h3 style="color:#FF1493;margin-bottom:0.5rem;font-size:1.1rem;">🌍 Where is it used?</h3><p style="line-height:2;color:var(--dark2);font-size:0.95rem;margin:0;">{where}</p></div>' if where else ''}
                    </div>""", unsafe_allow_html=True)
                
                with st.expander("📋 Detailed Summary", expanded=False):
                    core = result.get("core_concepts",{})
                    if core.get("definitions"):
                        st.markdown("#### 📚 Core Principles & Definitions")
                        for d in core["definitions"]:
                            t = d.replace(search_term,f"**{search_term}**") if search_term and search_term.lower() in d.lower() else d
                            p = t.split(". ",1) if ". " in t else [t, ""]
                            detail_text = p[1] if len(p) > 1 else ""
                            card_html = f"""<div class="detailed-item"><div class="detailed-item-bar"></div><div><strong>{p[0][:110]}</strong>{('<br><span style="color:#555;font-size:.9rem;">' + detail_text + '</span>') if detail_text else ''}</div></div>"""
                            st.markdown(card_html, unsafe_allow_html=True)
                    if core.get("mechanisms"):
                        st.markdown("#### ⚙️ Key Mechanisms & How It Works")
                        for m in core["mechanisms"]:
                            st.markdown(f"- {m.replace(search_term,f'**{search_term}**') if search_term and search_term.lower() in m.lower() else m}")
                    
                    # Only show formulas if they contain = or mathematical symbols
                    formulas_filtered = [f for f in core.get("formulas", []) if re.search(r'[=+\-*/^()\[\]]', f)]
                    if formulas_filtered:
                        st.markdown("#### 📐 Important Formulas")
                        for fi in formulas_filtered: st.markdown(f"- `{fi}`")
                    
                    if core.get("processes"):
                        st.markdown("#### 🔄 Step-by-Step Processes & Methods")
                        for pr in core["processes"]: st.markdown(f"- {pr}")

            elif active == "flashcards":
                st.markdown("""<div class="summary-card"><div class="summary-card-header"><h2 class="summary-card-title">Flashcards</h2><span class="summary-meta">Click "Show Answer" on any card</span></div></div>""", unsafe_allow_html=True)
                qa = result.get("active_recall",{}).get("qa_cards",[])
                if qa:
                    tot = len(qa)
                    mc = sum(1 for v in st.session_state.fc_status.values() if v=="Mastered")
                    lc = sum(1 for v in st.session_state.fc_status.values() if v=="Learning")
                    st.markdown(f"""<div class="fc-stats-bar"><span class="fc-stat fc-stat-mastered">✅ Mastered: {mc}</span><span class="fc-stat fc-stat-learning">📖 Learning: {lc}</span><span class="fc-stat fc-stat-new">🆕 New: {tot-mc-lc}</span></div>""", unsafe_allow_html=True)
                    for i, card in enumerate(qa):
                        status = st.session_state.fc_status.get(i,"New")
                        sc_map = {"Mastered":"#00C9A7","Learning":"#FF9F43","New":"#6C3CE1"}
                        st.markdown(f"""<div class="fc-card"><div class="fc-card-top"><span class="fc-card-num">Card {i+1} of {tot}</span><span class="flashcard-status" style="background:{sc_map.get(status,'#6C3CE1')};">{status}</span></div><p class="fc-card-question"><strong>Q:</strong> {card["question"]}</p></div>""", unsafe_allow_html=True)
                        if st.checkbox("Show Answer", key=f"fc_show_{i}"):
                            st.markdown(f"""<div class="flashcard-answer"><p style="color:#888;font-size:.85rem;font-weight:700;">Answer:</p><p style="color:var(--dark);font-weight:600;">{card["answer"]}</p></div>""", unsafe_allow_html=True)
                            b1, b2 = st.columns(2)
                            with b1:
                                if st.button("✅ Mastered", key=f"m_{i}", use_container_width=True):
                                    st.session_state.fc_status[i]="Mastered"
                                    st.session_state.mastered_cards=sum(1 for v in st.session_state.fc_status.values() if v=="Mastered")
                                    st.rerun()
                            with b2:
                                if st.button("📖 Learning", key=f"l_{i}", use_container_width=True):
                                    st.session_state.fc_status[i]="Learning"; st.rerun()
                else: st.info("No flashcards available")

        st.markdown("---")
        ph, pb = st.columns([3,1])
        with ph: st.markdown("""<div class="summary-card"><h2 class="summary-card-title">Personal Notes</h2><span class="summary-meta">Your custom annotations and thoughts</span></div>""", unsafe_allow_html=True)
        with pb: add_note = st.button("📝 Add Note", key="add_note_main", use_container_width=True, type="primary")
        if add_note or st.session_state.get("show_note_input", False):
            note_text = st.text_area("Write your note:", key="note_input", height=100)
            if st.button("Save Note", key="save_note"):
                if note_text.strip():
                    save_personal_note(user["id"], note_text.strip())
                    st.session_state.personal_notes = get_personal_notes(user["id"])
                    st.session_state.show_note_input = False; st.rerun()
        for i, note in enumerate(st.session_state.personal_notes):
            nc, dc = st.columns([10,1])
            with nc: st.markdown(f"""<div class="personal-note"><span class="note-timestamp">{note.get("time","")}</span><p style="margin:.5rem 0 0;color:var(--dark);font-weight:600;">{note["text"]}</p></div>""", unsafe_allow_html=True)
            with dc:
                if st.button("✕", key=f"del_note_{i}"):
                    delete_personal_note(note["id"], user["id"])
                    st.session_state.personal_notes = get_personal_notes(user["id"]); st.rerun()

        st.markdown("---")
        st.markdown("### 💾 Download Study Materials")
        d1, d2 = st.columns(2)
        with d1:
            if result.get("output_file") and os.path.exists(result["output_file"]):
                with open(result["output_file"],"rb") as f:
                    lbl = "📄 PDF" if result["output_file"].endswith(".pdf") else "📝 Markdown" if result["output_file"].endswith(".md") else "📄 Document"
                    st.download_button(f"Download {lbl}", f.read(), file_name=result["output_file"], mime="application/octet-stream", use_container_width=True)
        with d2:
            alt_fmt = st.selectbox("Convert to:", ["PDF","Markdown","Word"])
            if st.button("Convert & Download", use_container_width=True):
                with st.spinner(f"Converting to {alt_fmt}..."):
                    try:
                        from lecture_processor import export_to_pdf, export_to_markdown, export_to_word
                        nf = export_to_pdf(result) if alt_fmt=="PDF" else export_to_markdown(result) if alt_fmt=="Markdown" else export_to_word(result)
                        if os.path.exists(nf):
                            with open(nf,"rb") as f:
                                st.download_button(f"📥 Download {alt_fmt}", f.read(), file_name=nf, mime="application/octet-stream", use_container_width=True, key="converted_file")
                    except Exception as e: st.error(f"Conversion error: {e}")

        if "last_saved_id" not in st.session_state or st.session_state.get("last_saved_result") is not result:
            ok, nid = save_study_note(user["id"], result, st.session_state.get("input_method","unknown"))
            if ok:
                st.session_state.last_saved_id = nid
                st.session_state.last_saved_result = result
                st.session_state.history = get_user_notes(user["id"])


with tab2:
    st.markdown("### 📖 Study Materials History")
    st.caption("Your notes are saved to your account and persist across sessions.")
    if st.session_state.history:
        fc, tc, sc = st.columns([2,1,1])
        with fc: hs = st.text_input("Search history", placeholder="Title, timestamp, or overview keyword")
        with tc: ht = st.selectbox("Input Type", ["All","Mic","File","Pdf","Unknown"])
        with sc: hs2 = st.selectbox("Sort", ["Newest","Oldest"])
        fh = [e for e in st.session_state.history if ht=="All" or e.get("input_type","unknown").title()==ht]
        if hs.strip():
            sv = hs.strip().lower()
            fh = [e for e in fh if sv in e.get("title","").lower() or sv in e.get("timestamp","").lower() or sv in e.get("result",{}).get("concept_snapshot",{}).get("what","").lower()]
        fh = sorted(fh, key=lambda x: x.get("timestamp",""), reverse=(hs2=="Newest"))
        st.caption(f"Showing {len(fh)} of {len(st.session_state.history)} sessions")
        for i, item in enumerate(fh):
            nid = item.get("id")
            with st.expander(f"📚 {item.get('title', f'Study Session {i+1}')[:80]} — {item.get('timestamp','')}"):
                st.markdown(f"**Input Type:** {item.get('input_type','unknown').title()}")
                snap = item["result"].get("concept_snapshot",{})
                if snap and snap.get("what"): st.markdown(f"**Overview:** {snap['what'][:200]}...")
                diff = item["result"].get("difficulty",{})
                if diff:
                    ic = {"easy":"🟢","moderate":"🟡","advanced":"🔴"}
                    st.markdown(f"**Difficulty:** {ic.get(diff.get('level',''),'⚪')} {diff.get('label','N/A')}")
                qac = item["result"].get("active_recall",{}).get("qa_cards",[])
                if qac: st.markdown(f"**Flashcards:** {len(qac)} cards")
                st.markdown(f"**Key Points:** {len(item['result'].get('exam_insights',{}).get('faq_points',[])) + len(item['result'].get('applications',[]))}")
                bc1, bc2 = st.columns(2)
                with bc1:
                    if st.button("📖 View Notes", key=f"view_{i}", use_container_width=True):
                        st.session_state.current_result = item["result"]; st.rerun()
                with bc2:
                    if nid and st.button("🗑️ Delete", key=f"del_{i}", use_container_width=True):
                        if delete_study_note(nid, user["id"]):
                            st.session_state.history = get_user_notes(user["id"]); st.success("Deleted."); st.rerun()
        if not fh: st.info("No matching history items.")
    else: st.info("No study materials yet. Start creating your first set of notes!")


with tab3:
    st.markdown("### 📊 Study Analytics Dashboard")
    us = get_user_stats(user["id"])
    a1, a2, a3, a4 = st.columns(4)
    with a1: st.metric("Study Materials", us["total_notes"], "📚")
    with a2:
        tfc2 = sum(len(i["result"].get("active_recall",{}).get("qa_cards",[])) for i in st.session_state.history)
        st.metric("Total Flashcards", tfc2, "🃏")
    with a3:
        tkp = sum(len(i["result"].get("exam_insights",{}).get("faq_points",[]))+len(i["result"].get("applications",[])) for i in st.session_state.history)
        st.metric("Key Points", tkp, "💡")
    with a4:
        if st.session_state.history:
            ad = sum(i["result"].get("difficulty",{}).get("score",0) for i in st.session_state.history)/len(st.session_state.history)
            st.metric("Avg Difficulty", f"{ad:.0f}/100", "📊")
        else: st.metric("Avg Difficulty","N/A","📊")
    st.markdown("---")
    st.markdown("### 📈 Study Progress")
    if us["last_activity"]: st.caption(f"Last activity: {us['last_activity']}")
    st.info("💡 Tip: Use Flashcards regularly — spaced repetition improves retention by 80%!")
    if st.session_state.history:
        st.markdown("**Recent Study Sessions:**")
        for i, item in enumerate(st.session_state.history[:5],1):
            diff = item["result"].get("difficulty",{})
            icon = {"easy":"🟢","moderate":"🟡","advanced":"🔴"}.get(diff.get("level",""),"⚪")
            st.markdown(f"""<div class="session-item" style="margin-bottom:.5rem;">
                <span class="session-number">{i}</span>
                <div><strong>{item.get("input_type","unknown").title()}</strong>
                <br><span style="color:#888;font-size:.82rem;">{item.get("timestamp","")} {icon}</span></div>
            </div>""", unsafe_allow_html=True)


st.markdown("""
<div class="custom-footer">
    <p><strong>Exam Study Hub Generator</strong> • v4.0</p>
    <p>Empowering students with AI-powered study materials</p>
    <p style="font-size:.9rem;margin-top:.5rem;">Built with ♡ for Students • © 2026</p>
</div>
""", unsafe_allow_html=True)