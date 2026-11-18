"""A Keycloak account for each person in the DA register (keycloak_users.py)."""

import os
import unittest
from unittest import mock

from openg2p_registry_da_extension import keycloak_users as ku

CFG = {"attribute": "da_record_id", "initial_password": "", "roles": {}, "batch": 25, "max_attempts": 10,
       "retry_seconds": 600}
RECORD = {"internal_record_id": "rec-1", "functional_record_id": "DA-1000000001", "first_name": " Almaz ",
          "middle_name": "Kassa", "last_name": "Desta", "email": "Almaz.Kassa@Example.org", "position": "SUPERVISOR"}


class Admin:
    """Keycloak, as far as ensure_user uses it."""

    def __init__(self, users=None, keeps_attribute=True, taken_emails=()):
        self.users = {u["id"]: u for u in users or []}
        self.keeps_attribute, self.taken_emails = keeps_attribute, set(taken_emails)
        self.created, self.roles = [], []

    def find(self, **query):
        (key, value), = query.items()
        return next((u for u in self.users.values() if u.get(key) == value), None)

    def get(self, user_id):
        return self.users[user_id]

    def create(self, user):
        if user.get("email") in self.taken_emails or self.find(username=user["username"]):
            return None
        stored = {**user, "id": f"kc-{len(self.users) + 1}"}
        if not self.keeps_attribute:
            stored["attributes"] = {}
        self.users[stored["id"]] = stored
        self.created.append(user)
        return stored["id"]

    def set_attribute(self, user, name, value):
        if self.keeps_attribute:
            self.users[user["id"]] = {**self.users[user["id"]], "attributes": {name: [value]}}

    def give_roles(self, user_id, roles):
        self.roles.append((user_id, roles))


class UserTests(unittest.TestCase):
    def test_the_username_is_the_da_id_and_the_attribute_the_records_own_id(self):
        user = ku.user_representation(RECORD, CFG)
        self.assertEqual(user["username"], "DA-1000000001")
        self.assertEqual(user["attributes"], {"da_record_id": ["rec-1"]})
        self.assertEqual((user["firstName"], user["lastName"], user["email"]),
                         ("Almaz", "Kassa Desta", "almaz.kassa@example.org"))
        self.assertTrue(user["enabled"])

    def test_without_a_first_password_none_is_sent(self):
        self.assertNotIn("credentials", ku.user_representation(RECORD, CFG))

    def test_a_first_password_must_be_changed_at_the_first_sign_in(self):
        user = ku.user_representation(RECORD, {**CFG, "initial_password": "first-one"})
        self.assertEqual(user["credentials"], [{"type": "password", "value": "first-one", "temporary": True}])

    def test_a_test_environment_may_let_the_first_password_stay(self):
        user = ku.user_representation(RECORD, {**CFG, "initial_password": "first-one",
                                               "force_password_change": False})
        self.assertEqual(user["credentials"], [{"type": "password", "value": "first-one", "temporary": False}])

    def test_the_change_is_forced_unless_the_setting_says_false(self):
        for value, forced in (("", True), ("true", True), ("yes", True), ("FALSE", False), ("false", False)):
            with mock.patch.dict(os.environ, {"DA_KEYCLOAK_FORCE_PASSWORD_CHANGE": value}, clear=True):
                self.assertEqual(ku.settings()["force_password_change"], forced, value)

    def test_a_record_without_an_email_sends_none(self):
        self.assertNotIn("email", ku.user_representation({**RECORD, "email": None}, CFG))


class RoleTests(unittest.TestCase):
    MAPPING = {"*": ["da-services:User"], "SUPERVISOR": ["da-services:Supervisor", "offline_access"]}

    def test_a_position_gets_the_roles_of_everyone_and_its_own(self):
        self.assertEqual(ku.roles_for("SUPERVISOR", self.MAPPING),
                         [("da-services", "User"), ("da-services", "Supervisor"), (None, "offline_access")])

    def test_a_position_that_is_not_listed_gets_the_roles_of_everyone(self):
        self.assertEqual(ku.roles_for("ADMIN", self.MAPPING), [("da-services", "User")])
        self.assertEqual(ku.roles_for(None, {}), [])

    def test_a_setting_that_is_not_a_json_object_gives_no_roles(self):
        with self.assertLogs("da-keycloak-users", level="ERROR"):
            self.assertEqual(ku.role_mapping("not json"), {})
        with self.assertLogs("da-keycloak-users", level="ERROR"):
            self.assertEqual(ku.role_mapping('["a"]'), {})
        self.assertEqual(ku.role_mapping('{"*": ["a:b"], "X": "not a list"}'), {"*": ["a:b"]})


class EnsureUserTests(unittest.TestCase):
    def test_a_new_person_gets_an_account_with_their_roles(self):
        admin = Admin()
        cfg = {**CFG, "roles": {"SUPERVISOR": ["da-services:Supervisor"]}}
        user_id, status = ku.ensure_user(admin, RECORD, cfg)
        self.assertEqual(status, "CREATED")
        self.assertEqual(admin.users[user_id]["attributes"], {"da_record_id": ["rec-1"]})
        self.assertEqual(admin.roles, [(user_id, [("da-services", "Supervisor")])])

    def test_a_username_keycloak_already_has_is_linked_not_created_again(self):
        admin = Admin([{"id": "kc-9", "username": "DA-1000000001", "attributes": {}}])
        user_id, status = ku.ensure_user(admin, RECORD, CFG)
        self.assertEqual((user_id, status), ("kc-9", "LINKED"))
        self.assertEqual(admin.created, [])
        self.assertEqual(admin.users["kc-9"]["attributes"], {"da_record_id": ["rec-1"]})

    def test_an_email_keycloak_already_has_links_that_account(self):
        admin = Admin([{"id": "kc-3", "username": "almaz", "email": "almaz.kassa@example.org", "attributes": {}}],
                      taken_emails={"almaz.kassa@example.org"})
        user_id, status = ku.ensure_user(admin, RECORD, CFG)
        self.assertEqual((user_id, status), ("kc-3", "LINKED"))
        self.assertEqual(admin.users["kc-3"]["attributes"], {"da_record_id": ["rec-1"]})

    def test_an_account_that_belongs_to_another_record_is_not_taken_over(self):
        # Two records with one email: the second must not get the first one's account.
        admin = Admin([{"id": "kc-3", "username": "da-2000000002", "email": "almaz.kassa@example.org",
                        "attributes": {"da_record_id": ["rec-other"]}}],
                      taken_emails={"almaz.kassa@example.org"})
        with self.assertRaises(ValueError) as raised:
            ku.ensure_user(admin, RECORD, CFG)
        self.assertIn("already belongs to another record (rec-other)", str(raised.exception))
        self.assertEqual(admin.users["kc-3"]["attributes"], {"da_record_id": ["rec-other"]})
        self.assertEqual(admin.roles, [])

    def test_running_again_for_the_same_record_changes_nothing(self):
        admin = Admin()
        first = ku.ensure_user(admin, RECORD, CFG)
        second = ku.ensure_user(admin, RECORD, CFG)
        self.assertEqual((first[1], second[1], first[0]), ("CREATED", "LINKED", second[0]))
        self.assertEqual(len(admin.created), 1)

    def test_an_attribute_keycloak_does_not_keep_is_reported(self):
        with self.assertRaises(ValueError) as raised:
            ku.ensure_user(Admin(keeps_attribute=False), RECORD, CFG)
        self.assertIn("add it to the realm's user profile", str(raised.exception))


class SettingsTests(unittest.TestCase):
    def test_the_admin_address_follows_the_token_address(self):
        self.assertEqual(ku.admin_url_of("https://kc.example/realms/staff/protocol/openid-connect/token"),
                         "https://kc.example/admin/realms/staff")
        self.assertEqual(ku.admin_url_of("https://kc.example/auth/realms/staff/protocol/openid-connect/token"),
                         "https://kc.example/auth/admin/realms/staff")
        self.assertEqual(ku.admin_url_of("nonsense"), "")

    def test_it_is_off_until_switched_on(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(ku.settings()["enabled"])
        with mock.patch.dict(os.environ, {"DA_KEYCLOAK_USERS_ENABLED": "true"}, clear=True):
            self.assertTrue(ku.settings()["enabled"])

    def test_the_service_account_defaults_to_the_one_the_worker_already_has(self):
        env = {"REGISTRY_CELERY_WORKERS_MASTER_DATA_TOKEN_URL": "http://kc/realms/staff/protocol/openid-connect/token",
               "REGISTRY_CELERY_WORKERS_MASTER_DATA_CLIENT_ID": "da-registry-backend",
               "REGISTRY_CELERY_WORKERS_MASTER_DATA_CLIENT_SECRET": "s"}
        with mock.patch.dict(os.environ, env, clear=True):
            cfg = ku.settings()
        self.assertEqual((cfg["client_id"], cfg["admin_url"], cfg["attribute"]),
                         ("da-registry-backend", "http://kc/admin/realms/staff", "da_record_id"))

    def test_when_off_a_run_does_nothing_and_never_raises(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(ku, "sync_pending") as sync:
            ku.run_quietly()
        sync.assert_not_called()


class StatementTests(unittest.TestCase):
    def test_only_active_records_with_a_real_da_id_are_taken(self):
        self.assertIn("d.record_status = 'ACTIVE'", ku.PENDING)
        self.assertIn("NOT LIKE 'TEMP-%'", ku.PENDING)

    def test_a_record_already_done_is_not_taken_again_and_a_failure_waits_before_its_next_try(self):
        self.assertIn("k.internal_record_id IS NULL", ku.PENDING)
        self.assertIn("k.status = 'FAILED' AND k.attempts < :max_attempts", ku.PENDING)
        self.assertIn("make_interval(secs => :retry_seconds)", ku.PENDING)

    def test_the_table_is_created_only_when_missing_and_nothing_is_dropped(self):
        self.assertIn("CREATE TABLE IF NOT EXISTS", ku.CREATE_TABLE)
        for statement in (ku.CREATE_TABLE, ku.PENDING, ku.RECORD_OUTCOME):
            self.assertNotIn("DROP", statement)
            self.assertNotIn("g2p_register_das\" SET", statement)

    def test_the_first_password_is_never_logged(self):
        source = open(ku.__file__).read()
        for line in source.splitlines():
            if "_logger." in line:
                self.assertNotIn("password", line.lower())
                self.assertNotIn("credentials", line.lower())


if __name__ == "__main__":
    unittest.main()
