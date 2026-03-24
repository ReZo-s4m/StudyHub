import streamlit as st
from database import register_user, login_user, create_session, validate_session, destroy_all_user_sessions


def show_auth_page(embedded: bool = False):
    """Display a modern login/signup authentication page."""
    
    # Initialize auth mode
    if 'auth_mode' not in st.session_state:
        st.session_state.auth_mode = 'login'
    
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
        # Toggle buttons for Login / Sign Up
        if not embedded:
            toggle_col1, toggle_col2 = st.columns(2)
            with toggle_col1:
                if st.button(
                    "🔐 Login", 
                    key="toggle_login", 
                    use_container_width=True,
                    type="primary" if st.session_state.auth_mode == 'login' else "secondary"
                ):
                    st.session_state.auth_mode = 'login'
                    st.rerun()
            with toggle_col2:
                if st.button(
                    "✨ Sign Up", 
                    key="toggle_signup", 
                    use_container_width=True,
                    type="primary" if st.session_state.auth_mode == 'signup' else "secondary"
                ):
                    st.session_state.auth_mode = 'signup'
                    st.rerun()

            st.markdown("<div style='height: 0.5rem;'></div>", unsafe_allow_html=True)
        
        # ==================== LOGIN ====================
        if st.session_state.auth_mode == 'login':
            st.markdown("""
            <div class="auth-card fade-in">
                <div class="auth-card-header">
                    <h2 class="auth-card-title">Welcome Back 👋</h2>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            with st.form("login_form", clear_on_submit=False):
                st.markdown("##### 👤 Username")
                login_username = st.text_input(
                    "Username", 
                    placeholder="Enter your username", 
                    key="login_user",
                    label_visibility="collapsed"
                )
                
                st.markdown("##### 🔒 Password")
                login_password = st.text_input(
                    "Password", 
                    type="password", 
                    placeholder="Enter your password", 
                    key="login_pass",
                    label_visibility="collapsed"
                )
                
                st.markdown("<div style='height: 0.5rem;'></div>", unsafe_allow_html=True)
                login_btn = st.form_submit_button("→  Sign In", use_container_width=True)
                
                if login_btn:
                    if not login_username or not login_password:
                        st.error("⚠️ Please fill in all fields.")
                    else:
                        success, result = login_user(login_username, login_password)
                        if success:
                            # Create a persistent session token
                            session_token = create_session(result['id'])
                            st.session_state.authenticated = True
                            st.session_state.user = result
                            st.session_state.session_token = session_token
                            st.rerun()
                        else:
                            st.error(f"❌ {result}")
            
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
                    label_visibility="collapsed"
                )
                
                st.markdown("#####  Email")
                signup_email = st.text_input(
                    "Email", 
                    placeholder="you@example.com", 
                    key="signup_email",
                    label_visibility="collapsed"
                )
                
                st.markdown("##### 👤 Username")
                signup_username = st.text_input(
                    "Username", 
                    placeholder="Choose a unique username", 
                    key="signup_user",
                    label_visibility="collapsed"
                )
                
                col_pw1, col_pw2 = st.columns(2)
                with col_pw1:
                    st.markdown("##### 🔒 Password")
                    signup_password = st.text_input(
                        "Password", 
                        type="password", 
                        placeholder="Min 6 characters", 
                        key="signup_pass",
                        label_visibility="collapsed"
                    )
                with col_pw2:
                    st.markdown("##### 🔒 Confirm")
                    confirm_password = st.text_input(
                        "Confirm Password", 
                        type="password", 
                        placeholder="Re-enter password", 
                        key="signup_confirm",
                        label_visibility="collapsed"
                    )
                
                st.markdown("<div style='height: 0.5rem;'></div>", unsafe_allow_html=True)
                signup_btn = st.form_submit_button("→  Create Account", use_container_width=True)
                
                if signup_btn:
                    if not all([full_name, signup_email, signup_username, signup_password, confirm_password]):
                        st.error("⚠️ Please fill in all fields.")
                    elif len(signup_password) < 6:
                        st.error("⚠️ Password must be at least 6 characters.")
                    elif signup_password != confirm_password:
                        st.error("⚠️ Passwords do not match.")
                    elif "@" not in signup_email or "." not in signup_email:
                        st.error("⚠️ Please enter a valid email address.")
                    else:
                        success, message = register_user(signup_username, signup_email, signup_password, full_name)
                        if success:
                            st.success(f"✅ {message}")
                            st.session_state.auth_mode = 'login'
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
                <span>Passwords are encrypted &nbsp;•&nbsp; Your data stays private</span>
            </div>
            """, unsafe_allow_html=True)


def is_authenticated():
    """Check if user is currently authenticated."""
    return st.session_state.get('authenticated', False)


def get_current_user():
    """Get the currently logged-in user data."""
    return st.session_state.get('user', None)


def logout():
    """Log out the current user and destroy their session."""
    if st.session_state.get('session_token'):
        destroy_all_user_sessions(st.session_state['user']['id'])
    st.session_state.authenticated = False
    st.session_state.user = None
    st.session_state.session_token = None
    st.session_state.processing = False
    st.session_state.history = []
    st.session_state.current_result = None
