"""'Sign in with Hugging Face' — the server-side half of an
Authorization-Code-with-PKCE flow.

The token is never stored server-side: the browser holds it (sessionStorage) and
sends it in the Authorization header of each push, so the service keeps no push
credentials of its own (the point of moving off a shared server token). This
module only mints the CIMD document and proxies the code->token exchange +
userinfo, so the browser sidesteps CORS and the flow stays client-secret-free.

Two deploy knobs, both optional (env or `[project.<name>.export]` config):
- `hf_client_id` — a registered OAuth app's client id. Needed for localhost dev
  (HF can't fetch a CIMD doc from localhost); in prod, omit it and CIMD is used.
- `public_base_url` — the browser-visible base (e.g. https://ai.nls.uk/verify),
  used to build the CIMD client id and redirect uri. Falls back to the request's
  forwarded headers, then its Host.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

AUTHORIZE = "https://huggingface.co/oauth/authorize"
TOKEN = "https://huggingface.co/oauth/token"
WHOAMI = "https://huggingface.co/api/whoami-v2"
# Least privilege that still covers *create* a new dataset repo and *push* to an
# existing one, personal or org (the user picks which orgs to grant at consent).
SCOPES = "openid profile write-repos contribute-repos"
CALLBACK_PATH = "/oauth/callback/huggingface"


def base_url(cfg: dict, headers) -> str:
    """The browser-visible base URL, without trailing slash. Config/env wins;
    else reconstruct from proxy-forwarded headers (nginx), else the Host."""
    explicit = os.environ.get("PARATEXT_HF_PUBLIC_BASE_URL") or cfg.get("public_base_url")
    if explicit:
        return explicit.rstrip("/")
    proto = headers.get("x-forwarded-proto") or "http"
    host = headers.get("x-forwarded-host") or headers.get("host") or "localhost"
    prefix = (headers.get("x-forwarded-prefix") or "").rstrip("/")
    return f"{proto}://{host}{prefix}"


def client_id(cfg: dict, base: str) -> str:
    """The registered app's client id if configured, else the CIMD URL."""
    return (
        os.environ.get("PARATEXT_HF_CLIENT_ID")
        or cfg.get("hf_client_id")
        or f"{base}/.well-known/oauth-cimd"
    )


def cimd_document(base: str) -> dict:
    """The Client ID Metadata Document HF fetches to validate a registration-free
    (CIMD) client. Its client_id must equal the URL it's served from."""
    return {
        "client_id": f"{base}/.well-known/oauth-cimd",
        "client_name": "paratext review",
        "redirect_uris": [f"{base}{CALLBACK_PATH}"],
        "token_endpoint_auth_method": "none",
        "client_uri": base,
    }


def _post_form(url: str, data: dict) -> dict:
    req = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(data).encode(),
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def exchange_code(*, code: str, code_verifier: str, redirect_uri: str, client_id: str) -> dict:
    """Trade an authorization code (+ PKCE verifier) for an access token. Raises
    ValueError with HF's error body on a 4xx so the caller can surface it."""
    try:
        return _post_form(TOKEN, {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": code_verifier,
        })
    except urllib.error.HTTPError as e:
        raise ValueError(e.read().decode(errors="replace")) from e


def userinfo(token: str) -> dict:
    """The signed-in identity (name + orgs), so the UI can show who a push runs as."""
    req = urllib.request.Request(WHOAMI, headers={"authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)
