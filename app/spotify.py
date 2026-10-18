"""Single Spotify client: PKCE auth, token refresh, 429 backoff, typed errors."""
import base64
import hashlib
import json
import os
import secrets
import time
from urllib.parse import urlencode

import httpx

from app.env import ROOT

REDIRECT_URI = "http://127.0.0.1:8000/callback"
SCOPES = ("user-library-read user-top-read user-read-playback-state "
          "user-modify-playback-state user-read-currently-playing user-read-recently-played")
TOKENS = ROOT / ".tokens.json"
API = "https://api.spotify.com/v1"
ACCOUNTS = "https://accounts.spotify.com"


class SpotifyError(Exception):
    def __init__(self, status: int, reason: str, message: str = ""):
        super().__init__(f"{status} {reason} {message}".strip())
        self.status, self.reason, self.message = status, reason, message


class NoActiveDevice(SpotifyError): pass
class QuotaExceeded(SpotifyError): pass
class NotLoggedIn(Exception): pass


def client_id() -> str:
    return os.environ["SPOTIFY_CLIENT_ID"]


# --- PKCE ---------------------------------------------------------------

_pending: dict[str, str] = {}  # state -> code_verifier


def auth_url() -> str:
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    _pending[state] = verifier
    return f"{ACCOUNTS}/authorize?" + urlencode({
        "client_id": client_id(), "response_type": "code", "redirect_uri": REDIRECT_URI,
        "code_challenge_method": "S256", "code_challenge": challenge, "scope": SCOPES, "state": state,
    })


def exchange_code(code: str, state: str) -> None:
    verifier = _pending.pop(state, None)
    if not verifier:
        raise ValueError("unknown OAuth state; start again at /login")
    _token_request({"grant_type": "authorization_code", "code": code,
                    "redirect_uri": REDIRECT_URI, "code_verifier": verifier})


def _token_request(data: dict) -> dict:
    r = httpx.post(f"{ACCOUNTS}/api/token", data={**data, "client_id": client_id()}, timeout=15)
    r.raise_for_status()
    tok = r.json()
    old = _load_tokens() or {}
    tok.setdefault("refresh_token", old.get("refresh_token"))
    tok["expires_at"] = time.time() + tok["expires_in"] - 60
    TOKENS.write_text(json.dumps(tok))
    return tok


def _load_tokens() -> dict | None:
    return json.loads(TOKENS.read_text()) if TOKENS.exists() else None


def _access_token() -> str:
    tok = _load_tokens()
    if not tok:
        raise NotLoggedIn("visit http://127.0.0.1:8000/login")
    if time.time() >= tok["expires_at"]:
        tok = _token_request({"grant_type": "refresh_token", "refresh_token": tok["refresh_token"]})
    return tok["access_token"]


def logged_in() -> bool:
    return TOKENS.exists()


# --- API ----------------------------------------------------------------

def request(method: str, path: str, *, params=None, json_body=None, retries: int = 3):
    for _ in range(retries + 1):
        r = httpx.request(method, API + path, params=params, json=json_body, timeout=15,
                          headers={"Authorization": f"Bearer {_access_token()}"})
        if r.status_code == 429:
            time.sleep(int(r.headers.get("Retry-After", "5")))
            continue
        if r.status_code == 204 or not r.content:
            return None
        body = r.json() if "json" in r.headers.get("content-type", "") else {}
        if r.status_code >= 400:
            err = body.get("error", {}) if isinstance(body.get("error"), dict) else {}
            reason, msg = err.get("reason", ""), err.get("message", r.text[:200])
            if reason == "QUOTA_EXCEEDED":
                raise QuotaExceeded(r.status_code, reason, msg)
            if reason == "NO_ACTIVE_DEVICE" or (r.status_code == 404 and path.startswith("/me/player")):
                raise NoActiveDevice(r.status_code, reason or "NO_ACTIVE_DEVICE", msg)
            raise SpotifyError(r.status_code, reason, msg)
        return body
    raise SpotifyError(429, "RATE_LIMITED", "gave up after retries")


def saved_tracks(cap: int = 600) -> list[dict]:
    out, offset = [], 0
    while len(out) < cap:
        page = request("GET", "/me/tracks", params={"limit": 50, "offset": offset})
        out += [i["track"] for i in page["items"] if i.get("track")]
        if not page.get("next"):
            break
        offset += 50
    return out[:cap]


def top_tracks(time_range: str = "medium_term") -> list[dict]:
    return request("GET", "/me/top/tracks", params={"time_range": time_range, "limit": 50})["items"]


def recently_played() -> list[dict]:
    return request("GET", "/me/player/recently-played", params={"limit": 50})["items"]


def playback() -> dict | None:
    """None when nothing is playing (204)."""
    return request("GET", "/me/player")


def queue(uri: str) -> None:
    request("POST", "/me/player/queue", params={"uri": uri})


def next_track() -> None:
    request("POST", "/me/player/next")


def play(uris: list[str], position_ms: int = 0, device_id: str | None = None) -> None:
    params = {"device_id": device_id} if device_id else None
    request("PUT", "/me/player/play", params=params, json_body={"uris": uris, "position_ms": position_ms})


def pause() -> None:
    request("PUT", "/me/player/pause")


def devices() -> list[dict]:
    r = request("GET", "/me/player/devices")
    return (r or {}).get("devices", [])


def active_device_id() -> str | None:
    pb = playback()
    if pb and pb.get("device"):
        return pb["device"]["id"]
    for d in devices():
        if d.get("is_active"):
            return d["id"]
    for d in devices():
        if not d.get("is_restricted"):
            return d["id"]
    return None
