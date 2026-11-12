"""Give the sample approvers their declared password, permanently, after every install and upgrade.

The platform's keycloak-init creates the sample users with global.aweApproverUserPassword as a temporary
password (UPDATE_PASSWORD required) and skips users that already exist, so a fresh install cannot sign in as
alex.carter or nina.patel, and a changed value never reaches an existing user. This makes the declared
password the user's permanent password, the way the platform's functional-testing seed does
(reset-password with temporary false, then no required password update). Users that already sign in with
it are left alone. Nothing else on the user changes (enabled, roles, attributes).

Input: KEYCLOAK_URL, KEYCLOAK_USER and KEYCLOAK_PASSWORD (master realm, admin-cli), REALM, USERS (JSON list
of usernames), APPROVER_PASSWORD (empty: nothing to do), WAIT_SECONDS (how long to wait for keycloak-init to
create a user), DELAY_SECONDS. Passwords are never printed.
"""
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request


def call(method, url, token=None, form=None, body=None):
    headers, data = {}, None
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers, method=method), timeout=30) as r:
        raw = r.read()
    return json.loads(raw) if raw else None


def token(base, realm, user, password):
    form = {"grant_type": "password", "client_id": "admin-cli", "username": user, "password": password}
    return call("POST", f"{base}/realms/{urllib.parse.quote(realm)}/protocol/openid-connect/token", form=form)["access_token"]


def admin(base, deadline, delay):
    while True:
        try:
            return token(base, "master", os.environ["KEYCLOAK_USER"], os.environ["KEYCLOAK_PASSWORD"])
        except (urllib.error.URLError, KeyError, ValueError) as error:
            if time.monotonic() > deadline:
                raise SystemExit(f"Could not get a Keycloak admin token: {error}")
            print(f"Keycloak admin token not ready: {error}", flush=True)
            time.sleep(delay)


def signs_in(base, realm, username, password):
    try:
        token(base, realm, username, password)
        return True
    except urllib.error.HTTPError:
        return False


def main():
    base = os.environ["KEYCLOAK_URL"].rstrip("/")
    realm = os.environ.get("REALM", "staff")
    users = json.loads(os.environ.get("USERS", "[]"))
    password = os.environ.get("APPROVER_PASSWORD", "")
    delay = float(os.environ.get("DELAY_SECONDS", "10"))
    deadline = time.monotonic() + float(os.environ.get("WAIT_SECONDS", "600"))
    if not password or not users:
        print("No approver password or no users declared; nothing to do", flush=True)
        return 0
    users_url = f"{base}/admin/realms/{urllib.parse.quote(realm)}/users"
    pending = list(users)
    while pending:
        for username in list(pending):
            found = call("GET", f"{users_url}?{urllib.parse.urlencode({'username': username, 'exact': 'true'})}",
                         admin(base, deadline, delay))
            if not found:
                continue
            pending.remove(username)
            if signs_in(base, realm, username, password):
                print(f"{realm}/{username}: already signs in with the declared password", flush=True)
                continue
            user = found[0]
            tok = admin(base, deadline, delay)
            call("PUT", f"{users_url}/{user['id']}/reset-password", tok,
                 body={"type": "password", "value": password, "temporary": False})
            actions = [a for a in (user.get("requiredActions") or []) if a != "UPDATE_PASSWORD"]
            call("PUT", f"{users_url}/{user['id']}", tok, body={"requiredActions": actions})
            print(f"{realm}/{username}: password set (permanent)", flush=True)
        if pending:
            if time.monotonic() > deadline:
                # Not a failure: a release without the sample users (or keycloak-init off) is valid.
                print(f"{realm}: not created yet, left for the next upgrade: {', '.join(pending)}", flush=True)
                return 0
            print(f"{realm}: waiting for keycloak-init to create {', '.join(pending)}", flush=True)
            time.sleep(delay)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
