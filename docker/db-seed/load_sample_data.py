#!/usr/bin/env python3
"""Enter the sample Development Agents from openg2p-data and approve them at both stages.

Run by the platform's db-seed entrypoint when LOAD_SAMPLE_DATA=true (the
platform owns the hook; this is the DA variant's loader). Nothing is written
to the register tables: every sample DA is entered the way a person enters one
on the web form, through the staff API with a service account (client
credentials), and approved the way every register change is approved: the
approval request's stage 1 as INTAKE_SEED_APPROVER_1 (alex.carter) and its
stage 2 as INTAKE_SEED_APPROVER_2 (nina.patel), through the staff API's AWE
proxy. The approvers sign in as in the staff portal (staff IAM, then the
Keycloak login form, then IAM's callback) with the sample users' password the
chart passes (global.aweApproverUserPassword); no password grant, no Keycloak
change.

Data (openg2p-data, the COSS fork baked into the image at a pinned commit, or
a local checkout via OPENG2P_DATA_DIR):
  packs/<PACK>/samples/development_agents.json  DA-ID, Fayda FAN, qualification,
                                                specialisation, position, posting
  packs/<PACK>/samples/individuals.json         the people: names, gender,
                                                marital status, phone
  packs/<PACK>/migration/id_map.csv             pack P-code -> the id a Master
                                                Data seeded before the pack uses

Per DA: save the identity section (creates the submission), then contact,
service and location, then finalize. The DA-ID of the fixture is not sent;
the registry mints one after approval. A DA whose Fayda ID is already held by
a registered DA is skipped. Before entering one, the loader looks its Fayda ID up
in the registry database (PGHOST and the rest, which the seed job sets): a
submission of it still waiting for approval is approved rather than entered
again, and a draft a failed run left behind is completed and finalized, so
re-running loads nothing twice.

Approvals are restart-safe: the loader looks up the submission's open or
claimed task at whichever stage it has reached, so a stage approved by an
earlier run is not looked for again; a claim or a decision is sent once and,
when its answer is lost, the task is read again instead of resending it.

Only the loader's own submissions are ever resumed: the identity record of each
DA it enters has an id only the loader makes (uuid5 of the Fayda ID), and the
platform keeps that id. A submission somebody else entered for a sample person
(a tester's draft or pending one) is never completed or approved by the loader;
while it waits, the registry's uniqueness check reports the DA as already in
submission and the loader counts it as already present. (The platform records
the signed-in account as created_by, whatever the payload says, so created_by
cannot mark the loader's submissions.)

The submitter is the registry's service account (client credentials against
Keycloak, the registry's own client): a service identity, not a staff user, so
it does not go through the staff IAM sign-in. The approvers are staff users and
do.

Within the seed job's time (the deploy waits 15 minutes for the hook): the
clock starts with the loader. After INTAKE_SEED_TIME_BUDGET seconds (default
420) no further DA starts, and after INTAKE_SEED_HARD_LIMIT (default 660) no
request starts and no wait goes on (each try's timeout is cut to the time
left); what is left is counted and the next upgrade's seed continues it.

Requests cross the public ingress; a connection error, a timeout or a gateway
status (502, 503, 504) is retried with backoff. INTAKE_SEED_VERIFY_TLS=false
(what the chart sets) skips certificate checks. Sample data never fails the
upgrade it rides on: a DA that cannot be entered or approved (its kebele is
missing, a request keeps failing) is logged and counted and the others carry
on, and any failure before the first DA (a setting, an unreachable service, a
sign-in, the pack) is logged and the seed ends without sample DAs. The next seed run tries again.

The platform entrypoint seeds the approval workflow's policies after the
sample step; a submission cannot be finalized before they exist, so this
loader first applies the same idempotent AWE seed files (/seed/awe_meta_data,
upserts) when the AWE database settings are present.

Settings (env): the names the platform chart's db-seed job already sets when
dbSeed.loadSampleData is on, so a deployment needs nothing extra. The job
(registry chart 1.2.2-rc.614) names neither the staff IAM nor the Master Data
API; when STAFF_IAM_URL or MDS_API_URL is not set, the loader uses the public
host beside Keycloak's on the platform's host names: keycloak.<domain> (from
STAFF_TOKEN_URL) gives staff-iam.<domain> and master-data.<domain>.
  STAFF_API_URL, STAFF_TOKEN_URL, STAFF_CLIENT_ID, STAFF_CLIENT_SECRET
      the staff API and the registry's Keycloak client (global.authClientId);
      its service-account user needs the client role Intake Officer on the
      staff portal client
  STAFF_IAM_URL, INTAKE_SEED_PASSWORD, INTAKE_SEED_APPROVER_1 (alex.carter),
  INTAKE_SEED_APPROVER_2 (nina.patel), INTAKE_SEED_APPROVE_TIMEOUT (300)
      the approvers' sign-in (STAFF_IAM_URL: the staff IAM the approvers' browser
      would use, reachable from the job; Keycloak returns the sign-in to its
      public callback); without them nothing is submitted
  MDS_API_URL, MDS_TOKEN_URL, MDS_CLIENT_ID, MDS_CLIENT_SECRET
      Master Data API, read only (geography; the staff client's token unless
      MDS_CLIENT_ID is set)
  AWE_PGHOST, AWE_PGPORT, AWE_PGDATABASE, AWE_PGUSER, AWE_PGPASSWORD
  OPENG2P_DATA_DIR (default /openg2p-data), PACK (default ETH-OAN),
  STAFF_API_WAIT_SECONDS (default 600)
"""

import csv
import glob
import html
import http.cookiejar
import json
import os
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone

REGISTER_ID = "6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f90"
FORM_ID = "6f1c2d8e-4a7b-4c3e-9d2f-8b5a1e7c3f91"
SECTIONS = {
    "identity": "da_identity_section_01",
    "service": "da_service_section_02",
    "location": "da_location_section_03",
    "contact": "da_contact_section_04",
}
GEO_LEVELS = ("region", "zone", "woreda", "kebele")
CSRF = uuid.uuid4().hex
INTAKE_ARTIFACT = "registry.intake_form"
TRANSIENT_HTTP = (502, 503, 504)  # the gateway's answer when the service behind it is away
NETWORK_ATTEMPTS = 5
# Sent as created_by; the platform records the signed-in account's name instead (the service account).
SEED_CREATED_BY = "sample-data-seed"
# The identity record of every DA the loader enters has an id only the loader makes (uuid5 of the Fayda ID):
# a rerun resumes only its own submissions, never one somebody else entered for the same person.
SEED_RECORDS = uuid.UUID("0c4b2f61-93d7-4a8e-b5f2-6e1d7a9c3b58")
STARTED = time.time()  # the time limits count from here
# No DA is started after TIME_BUDGET seconds and no request after HARD_LIMIT (the hook waits 15 minutes).
TIME_BUDGET = int((os.environ.get("INTAKE_SEED_TIME_BUDGET") or "").strip() or 420)
HARD_LIMIT = int((os.environ.get("INTAKE_SEED_HARD_LIMIT") or "").strip() or 660)
REQUEST_TIMEOUT = 30  # seconds per try
TASK_PAGE_SIZE, TASK_PAGES = 100, 20
# The exact wording of the DA extension's Fayda uniqueness check (fayda_uniqueness.py).
ALREADY_REGISTERED, ALREADY_SUBMITTED = " is already registered as ", " is already in submission "


def log(msg: str) -> None:
    print(f"[load-sample-data] {msg}", flush=True)


def env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def beside_keycloak(name: str, label: str) -> str:
    """Setting `name`, or the public host <label>.<domain> beside Keycloak's keycloak.<domain>."""
    if env(name):
        return env(name).rstrip("/")
    token_url = urllib.parse.urlsplit(env("STAFF_TOKEN_URL"))
    first, _, domain = token_url.netloc.partition(".")
    if first != "keycloak" or not domain:
        return ""
    return f"{token_url.scheme}://{label}.{domain}"


def seed_record_id(fayda_id: str) -> str:
    """The identity record id of the sample DA with this Fayda ID: the same on every run."""
    return str(uuid.uuid5(SEED_RECORDS, f"da-sample/{fayda_id}"))


class OutOfTime(RuntimeError):
    """The loader's time is used: what is left waits for the next seed run."""


def time_left() -> float:
    return STARTED + HARD_LIMIT - time.time()


def read_json(path: str):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# ------------------------------------------------------------------ HTTP


def tls_context() -> ssl.SSLContext:
    """Certificates are checked unless INTAKE_SEED_VERIFY_TLS is false."""
    context = ssl.create_default_context()
    if env("INTAKE_SEED_VERIFY_TLS", "true").lower() == "false":
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


def fetch(opener, request, timeout: int = REQUEST_TIMEOUT,
          attempts: int = NETWORK_ATTEMPTS) -> tuple[int, object, bytes]:
    """Status, headers and body; network errors and gateway statuses are retried with backoff.

    A request that must not be applied twice is sent with attempts=1. No try starts after the hard limit,
    and none waits longer than the time left. The query is left out of what is logged: IAM's callback
    carries a one-time code there.
    """
    where = f"{request.get_method()} {request.full_url.split('?', 1)[0]}"
    for attempt in range(1, attempts + 1):
        left = time_left()
        if left <= 0:
            raise OutOfTime(f"{where}: not sent, the loader's {HARD_LIMIT}s are used")
        try:
            with opener.open(request, timeout=min(timeout, left)) as response:
                status, headers, body = response.status, response.headers, response.read()
        except urllib.error.HTTPError as exc:
            status, headers, body = exc.code, exc.headers, exc.read()
        except (urllib.error.URLError, OSError) as exc:
            if attempt == attempts:
                raise RuntimeError(f"{where}: {exc}") from exc
            status, headers, body = None, None, str(exc)
        if status is not None and (status not in TRANSIENT_HTTP or attempt == attempts):
            return status, headers, body
        wait = min(2 ** attempt, max(0, time_left()))
        log(f"{where}: {status or body}; again in {wait:.0f}s")
        time.sleep(wait)
    raise AssertionError("unreachable")


def http(url: str, data: bytes | None = None, headers: dict | None = None, timeout: int = REQUEST_TIMEOUT,
         attempts: int = NETWORK_ATTEMPTS):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method="POST" if data is not None else "GET")
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=tls_context()))
    status, _, body = fetch(opener, req, timeout, attempts)
    return status, body.decode("utf-8", "replace")


class Client:
    def __init__(self):
        self.staff = env("STAFF_API_URL").rstrip("/")
        self.master_data = beside_keycloak("MDS_API_URL", "master-data")
        self._tokens: dict[str, tuple[str, float]] = {}

    def token(self, kind: str) -> str:
        cached = self._tokens.get(kind)
        if cached and time.monotonic() < cached[1]:
            return cached[0]
        prefix = "STAFF" if kind == "staff" else "MDS"
        form = urllib.parse.urlencode({
            "grant_type": "client_credentials",
            "client_id": env(f"{prefix}_CLIENT_ID") or env("STAFF_CLIENT_ID"),
            "client_secret": env(f"{prefix}_CLIENT_SECRET") or env("STAFF_CLIENT_SECRET"),
        }).encode()
        code, body = http(env(f"{prefix}_TOKEN_URL") or env("STAFF_TOKEN_URL"), form,
                          {"Content-Type": "application/x-www-form-urlencoded"})
        if code != 200:
            raise RuntimeError(f"Keycloak refused the {kind} service token ({code}): {body[:200]}")
        data = json.loads(body)
        self._tokens[kind] = (data["access_token"], time.monotonic() + max(int(data.get("expires_in", 60)) - 30, 10))
        return data["access_token"]

    def call(self, base: str, path: str, payload: dict, pagination: dict | None = None, once: bool = False):
        envelope = {
            "request_header": {
                "request_id": uuid.uuid4().hex, "request_timestamp": datetime.now(timezone.utc).isoformat(),
                "sender_app_mnemonic": "da-registry-sample-data", "sender_app_url": "http://da-registry",
            },
            "request_body": {"request_payload": payload, "pagination_request": pagination},
        }
        code, body = http(base + path, json.dumps(envelope).encode(), {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + self.token("staff" if base == self.staff else "mds"),
            "X-CSRF-Token": CSRF, "Cookie": f"X-CSRF-Token={CSRF}",
        }, attempts=1 if once else NETWORK_ATTEMPTS)
        try:
            data = json.loads(body)
        except ValueError:
            return False, f"HTTP {code}: {body[:200]}", None
        header = data.get("response_header") or {}
        ok = code == 200 and header.get("response_status") == "SUCCESS"
        return ok, header.get("response_error_message") or (f"HTTP {code}" if not ok else ""), \
            (data.get("response_body") or {}).get("response_payload")

    def staff_ready(self, wait_seconds: int) -> bool:
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            try:
                code, _ = http(self.staff + "/docs", timeout=10)
                if code == 200:
                    return True
            except (RuntimeError, urllib.error.URLError, OSError):
                pass
            time.sleep(10)
        return False


# ------------------------------------------------------------- geography


def geo_index(client: Client) -> dict:
    """{level_value_id: node} from the Master Data API (one call per level)."""
    ok, err, levels = client.call(client.master_data, "/geo/get_all_geo_levels", {})
    if not ok:
        raise RuntimeError(f"Master Data geo levels: {err}")
    index = {}
    for level in levels or []:
        ok, err, rows = client.call(client.master_data, "/geo/get_geo_level_values",
                                    {"level_id": level["level_id"], "parent_level_value_id": None})
        if not ok:
            raise RuntimeError(f"Master Data geo values for {level['level_id']}: {err}")
        for row in rows or []:
            index[row["level_value_id"]] = {**row, "level_mnemonic": level.get("level_mnemonic") or ""}
    return index


def location(index: dict, id_map: dict, pcode: str):
    """The location section's geo fields for a pack P-code, or None."""
    for candidate in (pcode, id_map.get(pcode)):
        if candidate and candidate in index:
            chain, current = [], candidate
            while current in index:
                node = index[current]
                if (node["level_mnemonic"] or "").lower() in GEO_LEVELS:
                    chain.append({
                        "level": node["level_mnemonic"], "level_id": node["level_id"],
                        "level_mnemonic": node["level_mnemonic"], "level_value_id": node["level_value_id"],
                        "level_value_mnemonic": node["level_value_mnemonic"],
                    })
                current = node.get("parent_level_value_id")
            chain.reverse()
            return {"geo_lowest_level_value_id": candidate,
                    "geo_code_hierarchy_json": {"lowest_level_value_id": candidate, "hierarchy": chain}}
    return None


# ------------------------------------------------- earlier submissions


def registry_rows(sql: str, params: tuple) -> list[tuple] | None:
    """Rows from the registry database the seed job points at; None without it (a local run)."""
    if not (env("PGHOST") and env("PGDATABASE")):
        return None
    import psycopg2  # in the db-seed image; imported here so the tests need no driver

    conn = psycopg2.connect(host=env("PGHOST"), port=env("PGPORT", "5432"), dbname=env("PGDATABASE"),
                            user=env("PGUSER"), password=env("PGPASSWORD"))
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    finally:
        conn.close()


EARLIER_SQL = (
    "SELECT s.submission_id::text, s.draft_status, s.approval_status, f.internal_record_id::text"
    " FROM g2p_intake_form_das f JOIN g2p_intake_form_submissions s"
    " ON s.submission_id::text = f.submission_id::text"
    " WHERE f.internal_record_id::text = %s ORDER BY s.first_created_at DESC")


def earlier_submissions(fayda_id: str) -> list[tuple[str, str, str, str]]:
    """This loader's submissions of the sample DA (its own identity record id), newest first:
    (submission, draft, approval, intake record). Submissions others made for the person are not among them."""
    return registry_rows(EARLIER_SQL, (seed_record_id(fayda_id),)) or []


def approval_status(submission_id: str) -> str | None:
    rows = registry_rows("SELECT approval_status FROM g2p_intake_form_submissions WHERE submission_id::text = %s",
                         (submission_id,))
    return rows[0][0] if rows else None


# ------------------------------------------------------------ AWE policies


def seed_approval_policies() -> None:
    """Apply /seed/awe_meta_data/*.sql (idempotent upserts) so a submission can
    be finalized: the entrypoint seeds them only after the sample step."""
    host, db = env("AWE_PGHOST"), env("AWE_PGDATABASE")
    if not host or not db:
        log("AWE database settings not set: assuming the approval policies exist.")
        return
    files = sorted(glob.glob("/seed/awe_meta_data/*.sql"))
    run_env = {**os.environ, "PGHOST": host, "PGPORT": env("AWE_PGPORT", "5432"), "PGDATABASE": db,
               "PGUSER": env("AWE_PGUSER"), "PGPASSWORD": env("AWE_PGPASSWORD")}
    for path in files:
        done = subprocess.run(["psql", "-v", "ON_ERROR_STOP=1", "-q", "-f", path], env=run_env,
                              capture_output=True, text=True)
        if done.returncode:
            log(f"approval policies: {os.path.basename(path)} failed ({done.stderr.strip()[:200]}); "
                "assuming the policies the entrypoint seeds")
            return
    log(f"approval policies ensured ({len(files)} AWE seed files).")


# ------------------------------------------------------------------- main


def sections_for(da: dict, person: dict) -> dict:
    phone = person.get("phone") or ""
    mobile = da.get("mobile_number") or ("0" + phone[4:] if phone.startswith("+251") else phone or None)
    return {
        "identity": {
            "prefix": da.get("prefix"), "first_name": person.get("given_name") or da.get("first_name"),
            "middle_name": person.get("fathers_name") or da.get("middle_name"), "last_name": da.get("last_name"),
            "foundational_id": da["fayda_fan"], "gender": da.get("gender") or person.get("gender"),
            "marital_status": da.get("marital_status") or person.get("marital_status"),
            "birth_month_ec": da.get("birth_month_ec"), "birth_year_ec": da.get("birth_year_ec"),
        },
        "contact": {"mobile_number": mobile, "email": da.get("email"),
                    "telegram_number": da.get("telegram_number"), "alternate_number": da.get("alternate_number")},
        "service": {"education_level": da.get("education_level"), "specialisation": da.get("specialisation"),
                    "position": da.get("position"), "joined_date": da.get("joined_date")},
    }


def submit(client: Client, fields: dict, geo: dict, draft: tuple[str, str] | None = None) -> tuple[str, str]:
    """('submitted' | 'skipped' | 'pending' | 'failed', detail); `draft` (submission, record) is completed."""
    def save(section: str, record: dict, submission_id=None, record_id=""):
        action = "ADD" if submission_id is None else "UPDATE"
        payload = {k: v for k, v in record.items() if v not in (None, "")}
        # The save that creates the submission is sent once: a lost answer must not create a second draft
        # (the next run completes the first, found by its Fayda ID).
        return client.call(client.staff, "/intake-form-data/save_intake_form_submission", {
            "submission_id": submission_id, "section_id": SECTIONS[section], "section_register_id": REGISTER_ID,
            "form_id": FORM_ID, "register_id": REGISTER_ID, "created_by": SEED_CREATED_BY,
            "section_payload": [{"edit_action": action, "internal_record_id": record_id, "link_internal_record_id": "", **payload}],
        }, once=submission_id is None)

    if draft:
        submission_id, record_id = draft
        ok, err, _ = save("identity", fields["identity"], submission_id, record_id)
    else:
        own = seed_record_id(fields["identity"]["foundational_id"])
        ok, err, created = save("identity", fields["identity"], record_id=own)
        if ok:
            created = created or {}
            submission_id = created.get("submission_id")
            if not submission_id:
                return "failed", "saving the identity section returned no submission"
            records = [r for p in created.get("section_payloads") or [] for r in p.get("records") or []]
            record_id = (records[0].get("internal_record_id") if records else "") or own
    if not ok:
        if ALREADY_REGISTERED in err:
            return "skipped", err
        return ("pending" if ALREADY_SUBMITTED in err else "failed"), err
    for section, record in (("contact", fields["contact"]), ("service", fields["service"]), ("location", geo)):
        ok, err, _ = save(section, record, submission_id, record_id)
        if not ok:
            return "failed", f"{section}: {err}"
    ok, err, _ = client.call(client.staff, "/intake-form-data/finalize_intake_form_submission",
                             {"submission_id": submission_id}, once=True)
    return ("submitted", submission_id) if ok else ("failed", f"finalize: {err}")


# ------------------------------------------------------------- approval


class StaffSession:
    """One staff user signed in like the staff portal: IAM, the Keycloak login form, IAM's callback."""

    def __init__(self, iam_url: str, api_url: str, username: str, password: str):
        self.iam_url, self.api_url = iam_url.rstrip("/"), api_url.rstrip("/")
        self.username, self._password = username, password
        self._token = None
        self.sign_in()

    @staticmethod
    def _open(opener, request) -> tuple[int, object, bytes]:
        """Status, headers (looked up case-insensitively) and body, without following redirects."""
        return fetch(opener, request)

    def sign_in(self) -> None:
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None

        jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar), NoRedirect,
                                             urllib.request.HTTPSHandler(context=tls_context()))
        status, _, body = self._open(opener, urllib.request.Request(
            f"{self.iam_url}/auth/start_authentication_transaction?id=1&redirect_uri=/en", data=b"", method="POST"))
        if status != 200:
            raise RuntimeError(f"staff IAM did not start a sign-in for {self.username} ({status})")
        status, _, body = self._open(opener, urllib.request.Request(json.loads(body)["redirectUrl"] + "&prompt=login"))
        form = re.search(r'<form[^>]+id="kc-form-login"[^>]+action="([^"]+)"', body.decode("utf-8", "replace"))
        if status != 200 or not form:
            raise RuntimeError(f"no Keycloak login form for {self.username} ({status})")
        login = urllib.parse.urlencode({"username": self.username, "password": self._password, "credentialId": ""})
        status, headers, body = self._open(opener, urllib.request.Request(
            html.unescape(form.group(1)), data=login.encode(), method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"}))
        callback = headers.get("Location") or ""
        if not callback.startswith(f"{self.iam_url}/auth/callback"):
            said = " ".join(re.findall(r'kc-feedback-text[^>]*>([^<]+)', body.decode("utf-8", "replace")))
            raise RuntimeError(f"Keycloak refused the sign-in of {self.username} ({status}): {said.strip()[:200]}")
        status, _, _ = self._open(opener, urllib.request.Request(callback))
        token = next((c.value for c in jar if c.name == "X-Access-Token"), None)
        if status not in (302, 303, 307) or not token:
            raise RuntimeError(f"staff IAM issued no session for {self.username} ({status})")
        self._token = token
        log(f"signed in as {self.username}")

    def post(self, path: str, payload: dict, once: bool = False) -> dict:
        """The response payload; `once` for a request that must not be applied twice (no network retry)."""
        envelope = {
            "request_header": {"request_id": uuid.uuid4().hex,
                               "request_timestamp": datetime.now(timezone.utc).isoformat(),
                               "sender_app_mnemonic": "da-registry-sample-data", "sender_app_url": "http://da-registry"},
            "request_body": {"request_payload": payload, "pagination_request": {"current_page": 1, "page_size": 100}},
        }
        for attempt in (1, 2):
            csrf = uuid.uuid4().hex
            code, body = http(self.api_url + path, json.dumps(envelope).encode(), {
                "Content-Type": "application/json", "Authorization": f"Bearer {self._token}",
                "X-CSRF-Token": csrf, "Cookie": f"X-CSRF-Token={csrf}"}, attempts=1 if once else NETWORK_ATTEMPTS)
            try:
                data = json.loads(body)
            except ValueError:
                data = {}
            header = data.get("response_header") or {}
            if attempt == 1 and (code == 401 or str(header.get("response_error_code") or "").endswith("401")):
                self.sign_in()  # the session ended during a long run
                continue
            if code != 200 or header.get("response_status") != "SUCCESS":
                raise RuntimeError(f"{path} as {self.username}: {code} {header.get('response_error_code')} "
                                   f"{header.get('response_error_message')}")
            return (data.get("response_body") or {}).get("response_payload") or {}
        return {}


def open_task(approver, submission_id: str, stage: int) -> dict | None:
    """The approver's open or claimed task for this submission and stage, looked up page by page."""
    for status in ("open", "claimed"):
        for page in range(1, TASK_PAGES + 1):
            tasks = approver.post("/awe/list_my_tasks", {"status": status, "artifact_type": INTAKE_ARTIFACT,
                                                         "page": page, "page_size": TASK_PAGE_SIZE})
            items = (tasks.get("data") or {}).get("items") or []
            task = next((t for t in items
                         if t.get("artifact_id") == submission_id and int(t.get("stage_order") or 0) == stage), None)
            if task:
                return {"status": status, **task}
            if len(items) < TASK_PAGE_SIZE:
                break
    return None


def decide(approver, task: dict, submission_id: str, stage: int) -> bool:
    """Claim (when open) and approve, each sent once; False when an answer was lost."""
    try:
        if task.get("status", "open") == "open":
            approver.post("/awe/claim_task", {"task_id": task["id"]}, once=True)
        approver.post("/awe/submit_task_decision", {
            "task_id": task["id"], "action": "approve", "comment": "Sample data (db-seed)",
            "artifact_id": submission_id, "artifact_type": INTAKE_ARTIFACT, "current_stage": stage}, once=True)
    except OutOfTime:
        raise
    except RuntimeError as exc:
        log(f"  stage {stage} as {approver.username}: {exc}; reading the task again")
        return False
    log(f"  stage {stage} approved as {approver.username}")
    return True


def approve(approvers: list, submission_id: str, timeout: int) -> None:
    """Approve the submission at whichever stage it has reached: stage 1 as the first approver, stage 2 as the
    second. Done when the registry records it approved, or (without the database) when the last stage's
    decision went through."""
    deadline = min(time.time() + timeout, STARTED + HARD_LIMIT)
    while approval_status(submission_id) != "APPROVED":
        if time.time() > deadline:
            raise RuntimeError(f"submission {submission_id} is not approved within {timeout}s")
        decided = False
        for stage, approver in enumerate(approvers, 1):
            task = open_task(approver, submission_id, stage)
            if task:
                decided = decide(approver, task, submission_id, stage)
                if decided and stage == len(approvers) and approval_status(submission_id) is None:
                    return
                break
        if not decided:  # no task yet (AWE moves the submission on in the background), or the answer was lost
            time.sleep(3)


# ------------------------------------------------------------- main


def main() -> int:
    pack_dir = os.path.join(env("OPENG2P_DATA_DIR", "/openg2p-data"), "packs", env("PACK", "ETH-OAN"))
    fixture = os.path.join(pack_dir, "samples", "development_agents.json")
    if not os.path.exists(fixture):
        log(f"no sample DAs in this openg2p-data ({fixture}): nothing to submit.")
        return 0
    settings = {n: env(n) for n in ("STAFF_API_URL", "STAFF_TOKEN_URL", "STAFF_CLIENT_ID", "INTAKE_SEED_PASSWORD")}
    settings["MDS_API_URL"] = beside_keycloak("MDS_API_URL", "master-data")
    settings["STAFF_IAM_URL"] = beside_keycloak("STAFF_IAM_URL", "staff-iam")
    missing = [n for n, value in settings.items() if not value]
    if missing:
        log("missing settings " + ", ".join(missing) + ": sample DAs not submitted.")
        return 0
    doc = read_json(fixture)
    das = doc.get("development_agents") if isinstance(doc, dict) else doc
    people = {i["individual_id"]: i for i in read_json(os.path.join(pack_dir, "samples", "individuals.json"))}
    id_map = {}
    map_path = os.path.join(pack_dir, "migration", "id_map.csv")
    if os.path.exists(map_path):
        with open(map_path, encoding="utf-8", newline="") as fh:
            id_map = {row["pack_id"]: row["source_id"] for row in csv.DictReader(fh)}

    client = Client()
    if not client.staff_ready(min(int(env("STAFF_API_WAIT_SECONDS", "600")), int(TIME_BUDGET / 2))):
        log(f"staff API not reachable at {client.staff}: sample DAs not submitted.")
        return 0
    seed_approval_policies()
    log(f"staff IAM {settings['STAFF_IAM_URL']}, Master Data {settings['MDS_API_URL']}")
    try:
        approvers = [StaffSession(settings["STAFF_IAM_URL"], client.staff, env(name, default),
                                  env("INTAKE_SEED_PASSWORD"))
                     for name, default in (("INTAKE_SEED_APPROVER_1", "alex.carter"),
                                           ("INTAKE_SEED_APPROVER_2", "nina.patel"))]
    except Exception as exc:
        log(f"the approvers cannot sign in ({exc!r}): sample DAs not submitted.")
        return 0
    approve_timeout = int(env("INTAKE_SEED_APPROVE_TIMEOUT", "180"))
    try:
        index = geo_index(client)
    except Exception as exc:
        log(f"Master Data geography unavailable ({exc!r}): sample DAs not submitted.")
        return 0
    tally = {"approved": 0, "skipped": 0, "failed": 0, "left for the next run": 0}
    for da in das or []:
        if time.time() > STARTED + TIME_BUDGET:
            tally["left for the next run"] += 1
            continue
        try:
            outcome = load_one(client, approvers, approve_timeout, index, id_map, da,
                               people.get(da.get("individual_id")) or {})
        except Exception as exc:  # sample data must not fail the upgrade; the next run retries
            outcome = "left for the next run" if isinstance(exc, OutOfTime) or time_left() <= 0 else "failed"
            log(f"{da.get('da_id')}: {outcome if outcome == 'failed' else 'out of time'}, "
                f"left for the next run: {exc!r}")
        tally[outcome] += 1
    log(f"{tally['approved']} entered and approved, {tally['skipped']} already present, {tally['failed']} failed, "
        f"{tally['left for the next run']} left for the next run (of {len(das or [])} in pack "
        f"{env('PACK', 'ETH-OAN')}).")
    return 0


def load_one(client, approvers: list, approve_timeout: int, index: dict, id_map: dict, da: dict, person: dict) -> str:
    """Enter (or finish) one sample DA and approve it: 'approved', 'skipped' or 'failed'."""
    name = da.get("da_id")
    geo = location(index, id_map, da.get("geo_pcode") or "")
    if geo is None:
        log(f"{name}: kebele {da.get('geo_pcode')} not in Master Data; skipped")
        return "failed"
    earlier = earlier_submissions(da["fayda_fan"])
    waiting = next((sid for sid, status, approval, _ in earlier if status == "FINAL" and approval == "PENDING"), None)
    draft = next(((sid, rid) for sid, status, _, rid in earlier if status == "DRAFT"), None)
    if waiting:
        log(f"{name}: submission {waiting} waits for approval; approving it")
        submission_id = waiting
    else:
        outcome, detail = submit(client, sections_for(da, person), geo, draft)
        log(f"{name}: {outcome}{' (draft completed)' if draft and outcome == 'submitted' else ''} {detail}")
        if outcome != "submitted":
            return "skipped" if outcome in ("skipped", "pending") else "failed"
        submission_id = detail
    approve(approvers, submission_id, approve_timeout)
    return "approved"


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # a setting, the pack or a service: logged; the upgrade goes on
        log(f"FAILED before loading sample DAs, none loaded: {exc!r}")
