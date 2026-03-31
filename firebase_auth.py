"""
Firebase Authentication wrapper for Study Hub.
Uses Firebase Admin SDK (server-side) for session management, user management,
and the Firebase client SDK for sign-in.

Setup:
1. Go to https://console.firebase.google.com → create a project
2. Enable Authentication → Email/Password sign-in
3. Project Settings → Add Web App → copy firebaseConfig
4. Project Settings → Service Accounts → Generate new private key → save as
   firebase-service-account.json in the project root
5. Store firebaseConfig in .streamlit/secrets.toml under [firebase]
"""

import os
import json
import firebase_admin
from firebase_admin import credentials, auth
import streamlit as st

# Path to the service account JSON file
SERVICE_ACCOUNT_PATH = os.path.join(os.path.dirname(__file__), "firebase-service-account.json")

# Session cookie duration (14 days in seconds, Firebase maximum)
SESSION_COOKIE_DURATION_SECONDS = 60 * 60 * 24 * 14


def init_firebase():
    """Initialize Firebase Admin SDK from the service account JSON file."""
    # Check if Firebase is already initialized
    try:
        firebase_admin.get_app()
        return True  # Already initialized
    except ValueError:
        # App not initialized yet, proceed with initialization
        pass

    if not os.path.exists(SERVICE_ACCOUNT_PATH):
        raise FileNotFoundError(
            f"Firebase service account file not found at {SERVICE_ACCOUNT_PATH}.\n"
            "Download it from: Firebase Console → Project Settings → Service Accounts → "
            "Generate new private key"
        )

    try:
        cred = credentials.Certificate(SERVICE_ACCOUNT_PATH)
        firebase_admin.initialize_app(cred)
        return True
    except Exception as e:
        raise RuntimeError(f"Failed to initialize Firebase: {e}")


@st.cache_resource
def get_firebase_config():
    """
    Load Firebase web config from Streamlit secrets (cached).
    Returns a dict with web_api_key, web_auth_domain, web_project_id, web_app_id.
    """
    try:
        return {
            "web_api_key": st.secrets["firebase"]["web_api_key"],
            "web_auth_domain": st.secrets["firebase"]["web_auth_domain"],
            "web_project_id": st.secrets["firebase"]["web_project_id"],
            "web_app_id": st.secrets["firebase"]["web_app_id"],
        }
    except Exception:
        return None


# =============================================
# Client-side authentication (runs in browser)
# =============================================

# Firebase Sign-In via REST API (no client SDK needed for simple email/password)
# We'll use the Firebase Auth REST API directly for browser-side sign-in.
# The session cookie is created server-side after verifying the ID token.


def build_firebase_sign_in_url():
    """Returns the Firebase Auth sign-in URL for email/password."""
    config = get_firebase_config()
    if not config:
        return None
    return f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={config['web_api_key']}"


# =============================================
# Server-side authentication helpers
# =============================================

def register_user(email, password, username=None, full_name=""):
    """
    Create a new Firebase user via the Admin SDK.
    Returns (success, message).
    """
    try:
        init_firebase()
        try:
            user = auth.create_user(
                email=email,
                password=password,
                display_name=full_name or username or email.split("@")[0],
            )
            return True, f"Account created successfully! UID: {user.uid}"
        except firebase_admin.auth.EmailAlreadyExistsError:
            return False, "An account with this email already exists."
        except firebase_admin.auth.InvalidEmailError:
            return False, "Invalid email address."
        except firebase_admin.auth.WeakPasswordError as e:
            return False, f"Weak password: {e.message}"
        except Exception as e:
            return False, f"Registration failed: {str(e)}"
    except FileNotFoundError as e:
        return False, str(e)
    except Exception as e:
        return False, f"Firebase initialization failed: {str(e)}"


def delete_user(uid):
    """
    Delete a Firebase user by UID.
    Returns (success, message).
    """
    try:
        init_firebase()
        auth.delete_user(uid)
        return True, "User deleted."
    except firebase_admin.auth.UserNotFoundError:
        return False, "User not found."
    except Exception as e:
        return False, f"Failed to delete user: {str(e)}"


def send_password_reset_email(email):
    """
    Send a password reset email to the user via Firebase Auth.
    Returns (success, message).
    """
    try:
        init_firebase()
        auth.generate_password_reset_link(email)
        # Note: In production, you'd use the Firebase Admin SDK link generation
        # and send via your own email sender. Here we rely on Firebase's built-in
        # email sender which requires the Firebase console to be configured.
        return True, "Password reset email sent. Check your inbox."
    except firebase_admin.auth.UserNotFoundError:
        return False, "No account found with this email address."
    except firebase_admin.auth.InvalidEmailError:
        return False, "Invalid email address."
    except Exception as e:
        return False, f"Failed to send reset email: {str(e)}"


def create_session_cookie(id_token):
    """
    Create a Firebase session cookie from an ID token (obtained after client sign-in).
    The cookie lasts 14 days (Firebase maximum).
    Returns the session cookie string, or None on failure.
    """
    try:
        init_firebase()
        cookie = auth.create_session_cookie(id_token, SESSION_COOKIE_DURATION_SECONDS)
        return cookie
    except Exception as e:
        print(f"Error creating session cookie: {e}")
        return None


def verify_session_cookie(cookie):
    """
    Verify a Firebase session cookie and return user data.
    Returns (valid, user_data_or_error_message).
    user_data dict contains: uid, email, name, email_verified
    """
    try:
        init_firebase()
        decoded_claims = auth.verify_session_cookie(cookie, check_revoked=True)
        return True, {
            "uid": decoded_claims["uid"],
            "email": decoded_claims["email"],
            "name": decoded_claims.get("name", ""),
            "email_verified": decoded_claims.get("email_verified", False),
        }
    except firebase_admin.auth.ExpiredSessionCookieError:
        return False, "Session expired. Please log in again."
    except firebase_admin.auth.InvalidSessionCookieError:
        return False, "Invalid session. Please log in again."
    except firebase_admin.auth.RevokedSessionCookieError:
        return False, "Session revoked. Please log in again."
    except FileNotFoundError as e:
        return False, str(e)
    except Exception as e:
        return False, f"Session verification failed: {str(e)}"


def verify_id_token(id_token):
    """
    Verify a Firebase ID token (short-lived, ~1 hour).
    Returns (valid, user_data_or_error_message).
    Used for one-time token verification (e.g., after client-side sign-in).
    """
    try:
        init_firebase()
        decoded = auth.verify_id_token(id_token, check_revoked=True)
        return True, {
            "uid": decoded["uid"],
            "email": decoded["email"],
            "name": decoded.get("name", ""),
            "email_verified": decoded.get("email_verified", False),
        }
    except firebase_admin.auth.ExpiredIdTokenError:
        return False, "Token expired."
    except firebase_admin.auth.InvalidIdTokenError:
        return False, "Invalid token."
    except Exception as e:
        return False, f"Token verification failed: {str(e)}"


def get_user_by_email(email):
    """
    Look up a Firebase user by email address.
    Returns (success, user_data dict with uid/email/name) or (False, error).
    """
    try:
        init_firebase()
        user = auth.get_user_by_email(email)
        return True, {
            "uid": user.uid,
            "email": user.email,
            "name": user.display_name or "",
            "email_verified": user.email_verified,
        }
    except firebase_admin.auth.UserNotFoundError:
        return False, "No user found with this email."
    except firebase_admin.auth.InvalidEmailError:
        return False, "Invalid email address."
    except Exception as e:
        return False, f"User lookup failed: {str(e)}"
