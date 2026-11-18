"""A Keycloak user for each person in the DA register.

Everyone in the register (development agents, supervisors, officers, the
administrator) signs in to DA Services with a Keycloak account. Once a record
is approved and has its DA-ID, the celery worker creates that account:

- username: the DA-ID;
- first name, last name, email: from the record;
- an attribute (DA_KEYCLOAK_RECORD_ATTRIBUTE, "da_record_id") holding the
  record's internal_record_id, which the token carries so DA Services can open
  the record without searching for it;
- roles by position (DA_KEYCLOAK_ROLES);
- a first password (DA_KEYCLOAK_INITIAL_PASSWORD) that must be changed at the
  first sign-in, unless DA_KEYCLOAK_FORCE_PASSWORD_CHANGE is "false" (for a
  test environment). Without a first password the account has none and cannot
  sign in until one is set in Keycloak.

A username or an email that Keycloak already has is not created again: the
attribute and the roles are put on that account. An account that already
carries another record's id is left alone and the record fails with a reason:
two people in the register share an email, and one of them must be corrected.

It is off unless DA_KEYCLOAK_USERS_ENABLED is "true", so a deployment does
nothing until the service account has the rights and the settings are in.

When it runs: after the platform's worker task that gives a record its DA-ID,
and every DA_KEYCLOAK_RETRY_SECONDS for what failed (Keycloak down, a missing
right). What was done is kept in the table da_keycloak_users, one row per
record, so a record is not sent twice and a failure can be read
(status FAILED, last_error). A record that failed DA_KEYCLOAK_MAX_ATTEMPTS
times is left for an administrator.

Not covered: a later change of name, email or position is not carried to
Keycloak, and an account is not disabled when its record stops being active.

Settings (environment of the celery worker):
  DA_KEYCLOAK_USERS_ENABLED       "true" to switch it on
  DA_KEYCLOAK_ADMIN_URL           https://<keycloak>/admin/realms/<realm>;
                                  default: derived from the token URL
  DA_KEYCLOAK_TOKEN_URL, DA_KEYCLOAK_CLIENT_ID, DA_KEYCLOAK_CLIENT_SECRET
                                  the service account; default: the DA_AWE_*
                                  / Master Data client the worker already uses
                                  (register_domain/services/awe_service_token.py).
                                  It needs the realm-management roles
                                  manage-users, view-users, query-users and,
                                  for client roles, view-clients.
  DA_KEYCLOAK_RECORD_ATTRIBUTE    default "da_record_id"; must be an attribute
                                  of the realm's user profile
  DA_KEYCLOAK_INITIAL_PASSWORD    the first password; never logged
  DA_KEYCLOAK_FORCE_PASSWORD_CHANGE  "false" lets the first password stay
                                  (a test environment only); by default it
                                  must be changed at the first sign-in
  DA_KEYCLOAK_ROLES               JSON, position code -> roles, "*" for every
                                  position; a role is "client-id:Role name"
                                  or "realm role":
                                  {"*": ["da-services:User"], "SUPERVISOR": ["da-services:Supervisor"]}
  DA_KEYCLOAK_BATCH               records per run, default 25
  DA_KEYCLOAK_MAX_ATTEMPTS        default 10
  DA_KEYCLOAK_RETRY_SECONDS       default 600
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any

import httpx
from sqlalchemy import text

_logger = logging.getLogger("da-keycloak-users")

TABLE = "da_keycloak_users"
# The platform's worker tasks after which a record has its DA-ID.
TRIGGER_TASKS = frozenset({"functional_id_allocation_worker", "functional_id_updation_worker"})
# One run at a time across worker processes and replicas.
_ADVISORY_LOCK = 760417211

CREATE_TABLE = f"""
    CREATE TABLE IF NOT EXISTS "public"."{TABLE}" (
        internal_record_id VARCHAR PRIMARY KEY,
        functional_record_id VARCHAR,
        keycloak_user_id VARCHAR,
        status VARCHAR NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        last_error TEXT,
        updated_at TIMESTAMP NOT NULL DEFAULT now()
    )
"""

PENDING = f"""
    SELECT d.internal_record_id, d.functional_record_id, d.first_name, d.middle_name, d.last_name,
           d.email, d.position
    FROM "public"."g2p_register_das" d
    LEFT JOIN "public"."{TABLE}" k ON k.internal_record_id = d.internal_record_id
    WHERE d.record_status = 'ACTIVE'
      AND d.functional_record_id IS NOT NULL AND d.functional_record_id NOT LIKE 'TEMP-%'
      AND (k.internal_record_id IS NULL
           OR (k.status = 'FAILED' AND k.attempts < :max_attempts
               AND k.updated_at < now() - make_interval(secs => :retry_seconds)))
    ORDER BY d.created_at
    LIMIT :batch
"""

RECORD_OUTCOME = f"""
    INSERT INTO "public"."{TABLE}"
        (internal_record_id, functional_record_id, keycloak_user_id, status, attempts, last_error, updated_at)
    VALUES (:id, :da_id, :user_id, :status, 1, :error, now())
    ON CONFLICT (internal_record_id) DO UPDATE SET
        functional_record_id = EXCLUDED.functional_record_id,
        keycloak_user_id = COALESCE(EXCLUDED.keycloak_user_id, "{TABLE}".keycloak_user_id),
        status = EXCLUDED.status,
        attempts = "{TABLE}".attempts + 1,
        last_error = EXCLUDED.last_error,
        updated_at = now()
"""


class KeycloakUnavailable(RuntimeError):
    """Keycloak could not be reached or refused the service account: nothing
    about the record is wrong, so the run stops and no attempt is counted."""


def _text(name: str, default: str = "") -> str:
    return os.environ.get(name, "").strip() or default


def _number(name: str, default: int) -> int:
    try:
        return int(_text(name) or default)
    except ValueError:
        return default


def settings() -> dict:
    from .register_domain.services.awe_service_token import service_token_settings

    shared = service_token_settings()
    token_url = _text("DA_KEYCLOAK_TOKEN_URL", shared["token_url"])
    return {
        "enabled": _text("DA_KEYCLOAK_USERS_ENABLED").lower() == "true",
        "token_url": token_url,
        "client_id": _text("DA_KEYCLOAK_CLIENT_ID", shared["client_id"]),
        "client_secret": _text("DA_KEYCLOAK_CLIENT_SECRET", shared["client_secret"]),
        "admin_url": _text("DA_KEYCLOAK_ADMIN_URL", admin_url_of(token_url)).rstrip("/"),
        "attribute": _text("DA_KEYCLOAK_RECORD_ATTRIBUTE", "da_record_id"),
        "initial_password": os.environ.get("DA_KEYCLOAK_INITIAL_PASSWORD", ""),
        # Anything but "false" keeps the safe behaviour: a new password at the first sign-in.
        "force_password_change": _text("DA_KEYCLOAK_FORCE_PASSWORD_CHANGE").lower() != "false",
        "roles": role_mapping(_text("DA_KEYCLOAK_ROLES")),
        "batch": _number("DA_KEYCLOAK_BATCH", 25),
        "max_attempts": _number("DA_KEYCLOAK_MAX_ATTEMPTS", 10),
        "retry_seconds": _number("DA_KEYCLOAK_RETRY_SECONDS", 600),
    }


def admin_url_of(token_url: str) -> str:
    """https://kc/realms/staff/protocol/openid-connect/token -> https://kc/admin/realms/staff"""
    marker = "/realms/"
    if marker not in token_url:
        return ""
    base, rest = token_url.split(marker, 1)
    realm = rest.split("/", 1)[0]
    return f"{base}/admin/realms/{realm}" if realm else ""


def role_mapping(raw: str) -> dict[str, list[str]]:
    """The DA_KEYCLOAK_ROLES setting; anything that is not a JSON object of
    lists gives no roles and a logged error, never a stopped worker."""
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except ValueError:
        _logger.error("DA_KEYCLOAK_ROLES is not valid JSON; no roles will be given")
        return {}
    if not isinstance(value, dict):
        _logger.error("DA_KEYCLOAK_ROLES must be a JSON object of position -> roles; no roles will be given")
        return {}
    return {str(k): [str(r) for r in v] for k, v in value.items() if isinstance(v, list)}


def roles_for(position: str | None, mapping: dict[str, list[str]]) -> list[tuple[str | None, str]]:
    """(client id or None for a realm role, role name) for a position: the
    roles of "*" and then the position's own, each once."""
    found: list[tuple[str | None, str]] = []
    for name in mapping.get("*", []) + mapping.get(str(position or ""), []):
        client, _, role = name.rpartition(":")
        pair = (client.strip() or None, role.strip())
        if pair[1] and pair not in found:
            found.append(pair)
    return found


def user_representation(record: dict, cfg: dict) -> dict:
    """The Keycloak user of a register record. Ethiopian names are a given
    name, the father's and the grandfather's: the first is the first name, the
    other two the last name."""
    last = " ".join(str(record.get(k) or "").strip() for k in ("middle_name", "last_name")).strip()
    user: dict[str, Any] = {
        "username": str(record["functional_record_id"]),
        "enabled": True,
        "firstName": str(record.get("first_name") or "").strip(),
        "lastName": last,
        "attributes": {cfg["attribute"]: [str(record["internal_record_id"])]},
    }
    email = str(record.get("email") or "").strip().lower()
    if email:
        user["email"] = email
    if cfg.get("initial_password"):
        # temporary: Keycloak asks for a new password at the first sign-in.
        user["credentials"] = [{
            "type": "password", "value": cfg["initial_password"],
            "temporary": cfg.get("force_password_change", True),
        }]
    return user


class KeycloakAdmin:
    """The few Keycloak admin calls this needs, with the service account's token."""

    def __init__(self, cfg: dict, client: httpx.Client | None = None):
        self.cfg = cfg
        self.http = client or httpx.Client(timeout=20)
        self._token: str | None = None
        self._expires = 0.0
        self._clients: dict[str, str] = {}

    def _bearer(self) -> str:
        if self._token and time.time() < self._expires - 30:
            return self._token
        missing = [k for k in ("token_url", "client_id", "client_secret", "admin_url") if not self.cfg.get(k)]
        if missing:
            raise KeycloakUnavailable("settings missing: " + ", ".join(missing))
        try:
            response = self.http.post(self.cfg["token_url"], data={
                "grant_type": "client_credentials",
                "client_id": self.cfg["client_id"],
                "client_secret": self.cfg["client_secret"],
            })
        except httpx.HTTPError as error:
            raise KeycloakUnavailable(f"token request failed: {error}") from error
        if response.status_code >= 400:
            raise KeycloakUnavailable(f"the service account was refused a token ({response.status_code})")
        body = response.json()
        self._token = body["access_token"]
        self._expires = time.time() + int(body.get("expires_in", 300))
        return self._token

    def _call(self, method: str, path: str, **kwargs) -> httpx.Response:
        try:
            response = self.http.request(
                method, self.cfg["admin_url"] + path,
                headers={"Authorization": "Bearer " + self._bearer()}, **kwargs,
            )
        except httpx.HTTPError as error:
            raise KeycloakUnavailable(f"{method} {path} failed: {error}") from error
        if response.status_code in (401, 403):
            raise KeycloakUnavailable(
                f"the service account may not {method} {path.split('?')[0]} ({response.status_code}): "
                "it needs the realm-management roles manage-users, view-users, query-users and view-clients"
            )
        if response.status_code >= 500:
            raise KeycloakUnavailable(f"{method} {path.split('?')[0]} answered {response.status_code}")
        return response

    def find(self, **query: str) -> dict | None:
        response = self._call("GET", "/users", params={**query, "exact": "true"})
        users = response.json() if response.status_code == 200 else []
        return users[0] if users else None

    def get(self, user_id: str) -> dict:
        return self._call("GET", f"/users/{user_id}").json()

    def create(self, user: dict) -> str | None:
        """The new user's id; None when Keycloak already has the username or the email."""
        response = self._call("POST", "/users", json=user)
        if response.status_code == 409:
            return None
        if response.status_code >= 400:
            raise ValueError(f"Keycloak refused the user ({response.status_code}): {_reason(response)}")
        return response.headers.get("Location", "").rstrip("/").rsplit("/", 1)[-1] or None

    def set_attribute(self, user: dict, name: str, value: str) -> None:
        attributes = dict(user.get("attributes") or {})
        if attributes.get(name) == [value]:
            return
        attributes[name] = [value]
        response = self._call("PUT", f"/users/{user['id']}", json={**user, "attributes": attributes})
        if response.status_code >= 400:
            raise ValueError(f"Keycloak refused the attribute {name} ({response.status_code}): {_reason(response)}")

    def give_roles(self, user_id: str, roles: list[tuple[str | None, str]]) -> None:
        for client, role in roles:
            if client:
                client_uuid = self._client_uuid(client)
                found = self._call("GET", f"/clients/{client_uuid}/roles/{role}")
                target = f"/users/{user_id}/role-mappings/clients/{client_uuid}"
            else:
                found = self._call("GET", f"/roles/{role}")
                target = f"/users/{user_id}/role-mappings/realm"
            if found.status_code >= 400:
                raise ValueError(f"Keycloak has no role {role!r}" + (f" on client {client!r}" if client else ""))
            response = self._call("POST", target, json=[found.json()])
            if response.status_code >= 400:
                raise ValueError(f"Keycloak refused the role {role!r} ({response.status_code}): {_reason(response)}")

    def _client_uuid(self, client_id: str) -> str:
        if client_id not in self._clients:
            response = self._call("GET", "/clients", params={"clientId": client_id})
            clients = response.json() if response.status_code == 200 else []
            if not clients:
                raise ValueError(f"Keycloak has no client {client_id!r}")
            self._clients[client_id] = clients[0]["id"]
        return self._clients[client_id]


def _reason(response: httpx.Response) -> str:
    try:
        body = response.json()
        return str(body.get("errorMessage") or body.get("error_description") or body.get("error") or body)[:200]
    except ValueError:
        return response.text[:200]


def ensure_user(admin: KeycloakAdmin, record: dict, cfg: dict) -> tuple[str, str]:
    """(Keycloak user id, "CREATED" or "LINKED") for a register record."""
    wanted = user_representation(record, cfg)
    status = "LINKED"
    user = admin.find(username=wanted["username"])
    if user is None:
        user_id = admin.create(wanted)
        if user_id:
            status = "CREATED"
            user = admin.get(user_id)
        else:
            # Keycloak has the email under another username: that account is theirs.
            user = admin.find(email=wanted.get("email", "")) if wanted.get("email") else None
            if user is None:
                raise ValueError("Keycloak says the user exists, and no user has this DA-ID or this email")
    value = wanted["attributes"][cfg["attribute"]][0]
    held = (user.get("attributes") or {}).get(cfg["attribute"]) or []
    if held and held != [value]:
        # An account is one person's. Two records with one email would
        # otherwise take the account from each other in turn.
        raise ValueError(
            f"the Keycloak account {user.get('username')!r} already belongs to another record ({held[0]}): "
            "two people cannot share an email. Correct the email of one of them."
        )
    admin.set_attribute(user, cfg["attribute"], value)
    if (admin.get(user["id"]).get("attributes") or {}).get(cfg["attribute"]) != [value]:
        raise ValueError(
            f"Keycloak did not keep the attribute {cfg['attribute']!r}: add it to the realm's user profile"
        )
    admin.give_roles(user["id"], roles_for(record.get("position"), cfg["roles"]))
    return str(user["id"]), status


def sync_pending(engine, cfg: dict | None = None, admin: KeycloakAdmin | None = None) -> dict:
    """Create or link the Keycloak user of every record that still needs one,
    up to a batch. Returns counts by outcome."""
    cfg = cfg or settings()
    counts = {"CREATED": 0, "LINKED": 0, "FAILED": 0}
    with engine.connect() as conn:
        if not conn.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": _ADVISORY_LOCK}).scalar():
            return counts  # another worker is at it
        try:
            conn.execute(text(CREATE_TABLE))
            conn.commit()
            rows = conn.execute(text(PENDING), {
                "max_attempts": cfg["max_attempts"], "retry_seconds": cfg["retry_seconds"], "batch": cfg["batch"],
            }).mappings().all()
            if not rows:
                return counts
            admin = admin or KeycloakAdmin(cfg)
            for row in rows:
                record = dict(row)
                outcome = {"id": record["internal_record_id"], "da_id": record["functional_record_id"],
                           "user_id": None, "status": "FAILED", "error": None}
                try:
                    outcome["user_id"], outcome["status"] = ensure_user(admin, record, cfg)
                except KeycloakUnavailable as error:
                    _logger.warning("Keycloak users: stopped, %s (runs again later)", error)
                    break
                except Exception as error:  # noqa: BLE001 - one record's failure must not stop the others
                    outcome["error"] = str(error)[:500]
                    _logger.error("Keycloak user for %s failed: %s", record["functional_record_id"], outcome["error"])
                conn.execute(text(RECORD_OUTCOME), outcome)
                conn.commit()
                counts[outcome["status"]] += 1
        finally:
            conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _ADVISORY_LOCK})
            conn.commit()
    if any(counts.values()):
        _logger.info("Keycloak users: %s created, %s linked, %s failed",
                     counts["CREATED"], counts["LINKED"], counts["FAILED"])
    return counts


def run_quietly() -> None:
    """One run from the worker; never raises into the task that triggered it."""
    try:
        cfg = settings()
        if not cfg["enabled"]:
            return
        from openg2p_registry_celery_worker.engine import Engine

        sync_pending(Engine.get_engine(), cfg)
    except Exception as error:  # noqa: BLE001
        _logger.error("Keycloak users: run failed: %s", error)


def start_retry_timer() -> None:
    """A daemon thread in the worker's main process that runs again every
    DA_KEYCLOAK_RETRY_SECONDS, for records that failed while Keycloak was down."""
    cfg = settings()
    if not cfg["enabled"]:
        return

    def loop() -> None:
        while True:
            time.sleep(max(cfg["retry_seconds"], 60))
            run_quietly()

    threading.Thread(target=loop, name="da-keycloak-users", daemon=True).start()
