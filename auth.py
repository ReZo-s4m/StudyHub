import streamlit as st
import requests
import json
import time
from firebase_auth import (
    init_firebase,
    get_firebase_config,
    register_user as fb_register_user,
    create_session_cookie,
    verify_session_cookie,
    send_password_reset_email,
)
from database import get_or_create_local_user


FIREBASE_COOKIE_NAME = "firebase_session"
SESSION_COOKIE_DURATION_SECONDS = 60 * 60 * 24 * 14  # 14 days


# ============================================================
# Client-side cookie helpers (JavaScript embedded in Streamlit)
# ============================================================

def _cookie_script():
    return f"""
    <script>
    function setCookie(name, value, days) {{
        let expires = "";
        if (days) {{
            const d = new Date();
            d.setTime(d.getTime() + (days * 24 * 60 * 60 * 1000));
            expires = "; expires=" + d.toUTCString();
        }}
        document.cookie = name + "=" + (value || "") + expires + "; path=/; SameSite=Lax";
    }}
    function getCookie(name) {{
        const nameEQ = name + "=";
        const ca = document.cookie.split(';');
        for (let i = 0; i < ca.length; i++) {{
            let c = ca[i];
            while (c.charAt(0) == ' ') c = c.substring(1);
            if (c.indexOf(nameEQ) == 0) return c.substring(nameEQ.length);
        }}
        return null;
    }}
    function deleteCookie(name) {{
        document.cookie = name + '=; path=/; expires=Thu, 01 Jan 1970 00:00:00 UTC';
    }}
    window.setFirebaseCookie = setCookie;
    window.getFirebaseCookie = getCookie;
    window.deleteFirebaseCookie = deleteCookie;
    </script>
    """


def set_session_cookie_value(value):
    """Write the session cookie into the browser."""
    st.html(_cookie_script())
    days = SESSION_COOKIE_DURATION_SECONDS // (24 * 60 * 60)
    st.html(f"<script>window.setFirebaseCookie('{FIREBASE_COOKIE_NAME}', '{value}', {days});</script>")


def read_session_cookie_from_browser():
    """Read the firebase session cookie from the browser via JS interop."""
    st.html(_cookie_script())
    result_placeholder = st.empty()
    result_container = result_placeholder.container()
    result_area = st.empty()
    result_area.markdown(
        f"""
        <iframe id="cookie_reader" style="display:none;"></iframe>
        <script>
        (function() {{
            const val = window.getFirebaseCookie ? window.getFirebaseCookie('{FIREBASE_COOKIE_NAME}') : null;
            window.parent.postMessage({{type: 'firebase_cookie', value: val || ''}}, '*');
        }})();
        </script>
        """,
        unsafe_allow_html=True,
    )


def clear_session_cookie():
    """Delete the session cookie from the browser."""
    st.html(_cookie_script())
    st.html(f"<script>window.deleteFirebaseCookie('{FIREBASE_COOKIE_NAME}');</script>")


# ============================================================
# Firebase Auth REST API helpers
# ============================================================

def _get_firebase_api_key():
    config = get_firebase_config()
    if not config:
        raise ValueError(
            "Firebase config not found. Please add your Firebase web config to "
            ".streamlit/secrets.toml under [firebase]. See README for setup instructions."
        )
    return config["web_api_key"]


def _firebase_sign_in_rest(email, password):
    """Sign in via Firebase Auth REST API. Returns (success, full_response_dict or error_str)."""
    try:
        api_key = _get_firebase_api_key()
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={api_key}"
        payload = {"email": email, "password": password, "returnSecureToken": True}
        resp = requests.post(url, json=payload, timeout=30)
        data = resp.json()
        if resp.status_code == 200 and "idToken" in data:
            return True, data
        else:
            error_msg = data.get("error", {}).get("message", "Authentication failed.")
            error_map = {
                "INVALID_EMAIL": "Invalid email address.",
                "INVALID_PASSWORD": "Incorrect password.",
                "EMAIL_NOT_FOUND": "No account found with this email.",
                "USER_DISABLED": "This account has been disabled.",
                "TOO_MANY_ATTEMPTS_TRY_LATER": "Too many attempts. Please try again later.",
            }
            friendly = error_map.get(error_msg, error_msg.replace("_", " ").title())
            return False, friendly
    except requests.exceptions.Timeout:
        return False, "Request timed out. Check your internet connection."
    except Exception as e:
        return False, f"Authentication error: {str(e)}"


def _firebase_sign_up_rest(email, password, name=""):
    """Sign up (create account) via Firebase Auth REST API. Returns (success, full_response_dict or error_str)."""
    try:
        api_key = _get_firebase_api_key()
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={api_key}"
        payload = {"email": email, "password": password, "displayName": name, "returnSecureToken": True}
        resp = requests.post(url, json=payload, timeout=30)
        data = resp.json()
        if resp.status_code == 200 and "idToken" in data:
            return True, data
        else:
            error_msg = data.get("error", {}).get("message", "Sign-up failed.")
            error_map = {
                "EMAIL_EXISTS": "An account with this email already exists.",
                "INVALID_EMAIL": "Invalid email address.",
                "WEAK_PASSWORD": "Password must be at least 6 characters.",
                "TOO_MANY_ATTEMPTS_TRY_LATER": "Too many attempts. Please try again later.",
            }
            friendly = error_map.get(error_msg, error_msg.replace("_", " ").title())
            return False, friendly
    except requests.exceptions.Timeout:
        return False, "Request timed out. Check your internet connection."
    except Exception as e:
        return False, f"Sign-up error: {str(e)}"


# ============================================================
# Auth page UI
# ============================================================

def show_auth_page(embedded: bool = False):
    """Display a modern login/signup authentication page backed by Firebase Auth."""

    if "auth_mode" not in st.session_state:
        st.session_state.auth_mode = "login"

    if not embedded:
        st.markdown("""
        <div class="auth-wrapper">
            <div class="auth-floating-shapes">
                <div class="auth-shape auth-shape-1"></div>
                <div class="auth-shape auth-shape-2"></div>
                <div class="auth-shape auth-shape-3"></div>
            </div>
            <div class="auth-brand">
                <div class="auth-logo">📚</div>
                <h1 class="auth-brand-title">Exam Study Notes</h1>
                <p class="auth-brand-subtitle">AI-Powered Smart Study Material Generator</p>
            </div>
        </div>
        """, unsafe_allow_html=True)

        spacer_left, auth_col, spacer_right = st.columns([1, 2, 1])
    else:
        auth_col = st.container()

    with auth_col:
        if not embedded:
            toggle_col1, toggle_col2 = st.columns(2)
            with toggle_col1:
                if st.button(
                    "🔐 Login",
                    key="toggle_login",
                    use_container_width=True,
                    type="primary" if st.session_state.auth_mode == "login" else "secondary",
                ):
                    st.session_state.auth_mode = "login"
                    st.rerun()
            with toggle_col2:
                if st.button(
                    "✨ Sign Up",
                    key="toggle_signup",
                    use_container_width=True,
                    type="primary" if st.session_state.auth_mode == "signup" else "secondary",
                ):
                    st.session_state.auth_mode = "signup"
                    st.rerun()

            st.markdown("<div style='height: 0.5rem;'></div>", unsafe_allow_html=True)

        # ==================== LOGIN ====================
        if st.session_state.auth_mode == "login":
            st.markdown("""
            <div class="auth-card fade-in">
                <div class="auth-card-header">
                    <h2 class="auth-card-title">Welcome Back 👋</h2>
                </div>
            </div>
            """, unsafe_allow_html=True)

            with st.form("login_form", clear_on_submit=False):
                st.markdown("##### 👤 Email")
                login_email = st.text_input(
                    "Email",
                    placeholder="you@example.com",
                    key="login_email",
                    label_visibility="collapsed",
                )

                st.markdown("##### 🔒 Password")
                login_password = st.text_input(
                    "Password",
                    type="password",
                    placeholder="Enter your password",
                    key="login_pass",
                    label_visibility="collapsed",
                )

                st.markdown("<div style='height: 0.5rem;'></div>", unsafe_allow_html=True)
                login_btn = st.form_submit_button("→  Sign In", use_container_width=True)

                if login_btn:
                    if not login_email or not login_password:
                        st.error("⚠️ Please fill in all fields.")
                    else:
                        # Sign in via Firebase REST API
                        success, result = _firebase_sign_in_rest(login_email, login_password)
                        if success:
                            # Create server-side session cookie from the ID token
                            id_token = result["idToken"]
                            firebase_uid = result.get("localId", "")
                            display_name = result.get("displayName", "")
                            session_cookie = create_session_cookie(id_token)
                            if not session_cookie:
                                st.error("❌ Failed to create session. Please try again.")
                            else:
                                # Map Firebase user to local DB record
                                local_user_id, _ = get_or_create_local_user(
                                    firebase_uid=firebase_uid,
                                    email=login_email,
                                    name=display_name,
                                )
                                st.session_state.authenticated = True
                                st.session_state.user = {
                                    "id": local_user_id,
                                    "uid": firebase_uid,
                                    "email": login_email,
                                    "name": display_name,
                                }
                                st.session_state.session_cookie = session_cookie
                                set_session_cookie_value(session_cookie)
                                st.rerun()
                        else:
                            st.error(f"❌ {result}")

            # Password reset link
            with st.expander("Forgot password?"):
                reset_email = st.text_input("Enter your email address", key="reset_email_input")
                if st.button("Send Reset Email"):
                    if reset_email:
                        ok, msg = send_password_reset_email(reset_email)
                        if ok:
                            st.success(f"✅ {msg}")
                        else:
                            st.error(f"❌ {msg}")

            if not embedded:
                st.markdown("""
                <div class="auth-footer-text">
                    <p>Don't have an account? Click <strong>Sign Up</strong> above</p>
                </div>
                """, unsafe_allow_html=True)

        # ==================== SIGN UP ====================
        else:
            st.markdown("""
            <div class="auth-card fade-in">
                <div class="auth-card-header">
                    <h2 class="auth-card-title">Create Account ✨</h2>
                    <p class="auth-card-desc">Join and start generating smart study notes</p>
                </div>
            </div>
            """, unsafe_allow_html=True)

            with st.form("signup_form", clear_on_submit=True):
                st.markdown("#####  Full Name")
                full_name = st.text_input(
                    "Full Name",
                    placeholder="Enter your full name",
                    key="signup_name",
                    label_visibility="collapsed",
                )

                st.markdown("#####  Email")
                signup_email = st.text_input(
                    "Email",
                    placeholder="you@example.com",
                    key="signup_email",
                    label_visibility="collapsed",
                )

                col_pw1, col_pw2 = st.columns(2)
                with col_pw1:
                    st.markdown("##### 🔒 Password")
                    signup_password = st.text_input(
                        "Password",
                        type="password",
                        placeholder="Min 6 characters",
                        key="signup_pass",
                        label_visibility="collapsed",
                    )
                with col_pw2:
                    st.markdown("##### 🔒 Confirm")
                    confirm_password = st.text_input(
                        "Confirm Password",
                        type="password",
                        placeholder="Re-enter password",
                        key="signup_confirm",
                        label_visibility="collapsed",
                    )

                st.markdown("<div style='height: 0.5rem;'></div>", unsafe_allow_html=True)
                signup_btn = st.form_submit_button("→  Create Account", use_container_width=True)

                if signup_btn:
                    if not all([full_name, signup_email, signup_password, confirm_password]):
                        st.error("⚠️ Please fill in all fields.")
                    elif len(signup_password) < 6:
                        st.error("⚠️ Password must be at least 6 characters.")
                    elif signup_password != confirm_password:
                        st.error("⚠️ Passwords do not match.")
                    elif "@" not in signup_email or "." not in signup_email:
                        st.error("⚠️ Please enter a valid email address.")
                    else:
                        # Register via Firebase Admin SDK (server-side)
                        success, message = fb_register_user(signup_email, signup_password, full_name)
                        if success:
                            # Auto sign-in after successful registration
                            sig_ok, sign_up_data = _firebase_sign_up_rest(signup_email, signup_password, full_name)
                            if sig_ok:
                                id_token = sign_up_data["idToken"]
                                firebase_uid = sign_up_data.get("localId", "")
                                session_cookie = create_session_cookie(id_token)
                                if session_cookie:
                                    # Map Firebase user to local DB record
                                    local_user_id, _ = get_or_create_local_user(
                                        firebase_uid=firebase_uid,
                                        email=signup_email,
                                        name=full_name,
                                    )
                                    st.session_state.authenticated = True
                                    st.session_state.user = {
                                        "id": local_user_id,
                                        "uid": firebase_uid,
                                        "email": signup_email,
                                        "name": full_name,
                                    }
                                    st.session_state.session_cookie = session_cookie
                                    set_session_cookie_value(session_cookie)
                                    st.success("✅ Account created! Signed in automatically.")
                                    st.rerun()
                                else:
                                    st.success("✅ Account created! Please log in.")
                                    st.session_state.auth_mode = "login"
                                    st.rerun()
                            else:
                                st.success("✅ Account created! Please log in.")
                                st.session_state.auth_mode = "login"
                                st.rerun()
                        else:
                            st.error(f"❌ {message}")

            if not embedded:
                st.markdown("""
                <div class="auth-footer-text">
                    <p>Already have an account? Click <strong>Login</strong> above</p>
                </div>
                """, unsafe_allow_html=True)

        if not embedded:
            st.markdown("""
            <div class="auth-security-badge">
                <span>🔐</span>
                <span>Secured by Firebase Authentication &nbsp;•&nbsp; Your data stays private</span>
            </div>
            """, unsafe_allow_html=True)


def _get_uid_from_id_token(id_token):
    """Decode the UID from a Firebase ID token (without full verification)."""
    try:
        import jwt
        # Firebase ID tokens are JWTs; decode without verification to extract the UID
        # The token is verified server-side via create_session_cookie
        decoded = jwt.decode(id_token, options={"verify_signature": False})
        return decoded.get("user_id") or decoded.get("sub", "")
    except Exception:
        return ""


# ============================================================
# Session helpers
# ============================================================

def is_authenticated():
    """Check if user is currently authenticated (checks session_state)."""
    return st.session_state.get("authenticated", False)


def get_current_user():
    """Get the currently logged-in user data from session state."""
    return st.session_state.get("user", None)


def logout():
    """Log out the current user — clear session cookie and local state."""
    clear_session_cookie()
    st.session_state.authenticated = False
    st.session_state.user = None
    st.session_state.session_cookie = None
    st.session_state.processing = False
    st.session_state.history = []
    st.session_state.current_result = None
