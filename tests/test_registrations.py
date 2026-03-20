"""
Registration workflow tests — submit, verify, admin CRUD, approve, reject,
set-password, forgot-password.
"""
import hashlib
from unittest.mock import patch, call

from r2lab_api.models.registration import RegistrationStatus
from r2lab_api.models.user import UserStatus

from tests.conftest import auth, _make_user


REG_DATA = {
    "email": "prospect@example.com",
    "first_name": "Ada",
    "last_name": "Lovelace",
    "affiliation": "INRIA",
    "purpose": "Wireless research",
}


def _submit(client):
    """Submit a registration and return (response, captured_token_hash)."""
    with patch("r2lab_api.routers.registrations.send_mail") as mock_mail:
        r = client.post("/registrations", json=REG_DATA)
    return r, mock_mail


def _extract_token_from_mail(mock_mail):
    """Pull the raw token out of the verification email body."""
    body = mock_mail.call_args.kwargs["body"]
    for line in body.splitlines():
        if "token=" in line:
            return line.strip().split("token=")[1]
    raise ValueError("No token found in email body")


# ---------- Submit ----------

class TestSubmitRegistration:

    def test_submit_returns_201(self, client, db):
        r, _ = _submit(client)
        assert r.status_code == 201

    def test_submit_sends_verification_email(self, client, db):
        _, mock_mail = _submit(client)
        mock_mail.assert_called_once()
        assert mock_mail.call_args.kwargs["to"] == REG_DATA["email"]
        assert "verify" in mock_mail.call_args.kwargs["subject"].lower()

    def test_submit_duplicate_pending_rejected(self, client, db):
        _submit(client)
        with patch("r2lab_api.routers.registrations.send_mail"):
            r = client.post("/registrations", json=REG_DATA)
        assert r.status_code == 409

    def test_submit_existing_user_rejected(self, client, db):
        _make_user(db, email=REG_DATA["email"])
        with patch("r2lab_api.routers.registrations.send_mail"):
            r = client.post("/registrations", json=REG_DATA)
        assert r.status_code == 409

    def test_submit_after_rejection_allowed(self, client, db, admin_token):
        """A previously rejected email can re-register."""
        r, mock_mail = _submit(client)
        token = _extract_token_from_mail(mock_mail)
        with patch("r2lab_api.routers.registrations.send_mail"):
            client.post("/registrations/verify", json={"token": token})
        # reject it
        with patch("r2lab_api.routers.registrations.send_mail"):
            client.post(
                "/registrations/1/reject",
                json={"comment": "no"},
                headers=auth(admin_token),
            )
        # re-submit should work
        with patch("r2lab_api.routers.registrations.send_mail"):
            r = client.post("/registrations", json=REG_DATA)
        assert r.status_code == 201


# ---------- Verify ----------

class TestVerifyEmail:

    def test_verify_sets_pending_admin(self, client, db):
        _, mock_mail = _submit(client)
        token = _extract_token_from_mail(mock_mail)
        with patch("r2lab_api.routers.registrations.send_mail"):
            r = client.post("/registrations/verify", json={"token": token})
        assert r.status_code == 200

    def test_verify_notifies_admins(self, client, db, admin_user):
        _, mock_mail = _submit(client)
        token = _extract_token_from_mail(mock_mail)
        with patch("r2lab_api.routers.registrations.send_mail") as notify:
            client.post("/registrations/verify", json={"token": token})
        notify.assert_called_once()
        from r2lab_api.config import settings
        assert notify.call_args.kwargs["to"] == settings.admin_email

    def test_verify_invalid_token(self, client, db):
        _submit(client)
        r = client.post("/registrations/verify", json={"token": "bogus"})
        assert r.status_code == 400

    def test_verify_token_cannot_be_reused(self, client, db):
        _, mock_mail = _submit(client)
        token = _extract_token_from_mail(mock_mail)
        with patch("r2lab_api.routers.registrations.send_mail"):
            client.post("/registrations/verify", json={"token": token})
        r = client.post("/registrations/verify", json={"token": token})
        assert r.status_code == 400


# ---------- Admin list / detail / delete ----------

class TestAdminCRUD:

    def _verified_reg(self, client, db):
        _, mock_mail = _submit(client)
        token = _extract_token_from_mail(mock_mail)
        with patch("r2lab_api.routers.registrations.send_mail"):
            client.post("/registrations/verify", json={"token": token})

    def test_list_requires_admin(self, client, db, user_token):
        r = client.get("/registrations", headers=auth(user_token))
        assert r.status_code == 403

    def test_list_all(self, client, db, admin_token):
        self._verified_reg(client, db)
        r = client.get("/registrations", headers=auth(admin_token))
        assert r.status_code == 200
        assert len(r.json()) == 1

    def test_list_filter_status(self, client, db, admin_token):
        self._verified_reg(client, db)
        r = client.get(
            "/registrations", params={"status": "pending_admin"},
            headers=auth(admin_token),
        )
        assert len(r.json()) == 1
        r = client.get(
            "/registrations", params={"status": "pending_email"},
            headers=auth(admin_token),
        )
        assert len(r.json()) == 0

    def test_get_detail(self, client, db, admin_token):
        self._verified_reg(client, db)
        r = client.get("/registrations/1", headers=auth(admin_token))
        assert r.status_code == 200
        assert r.json()["email"] == REG_DATA["email"]

    def test_delete(self, client, db, admin_token):
        self._verified_reg(client, db)
        r = client.delete("/registrations/1", headers=auth(admin_token))
        assert r.status_code == 204
        r = client.get("/registrations", headers=auth(admin_token))
        assert len(r.json()) == 0


# ---------- Approve ----------

class TestApprove:

    def _pending_admin_reg(self, client, db):
        _, mock_mail = _submit(client)
        token = _extract_token_from_mail(mock_mail)
        with patch("r2lab_api.routers.registrations.send_mail"):
            client.post("/registrations/verify", json={"token": token})

    def test_approve_creates_user(self, client, db, admin_token):
        self._pending_admin_reg(client, db)
        with patch("r2lab_api.routers.registrations.send_mail"):
            r = client.post(
                "/registrations/1/approve",
                json={"slice_name": "inria_test"},
                headers=auth(admin_token),
            )
        assert r.status_code == 200
        user = r.json()
        assert user["email"] == REG_DATA["email"]
        assert user["first_name"] == REG_DATA["first_name"]
        assert user["status"] == "approved"

    def test_approve_creates_slice_and_membership(
        self, client, db, admin_token,
    ):
        self._pending_admin_reg(client, db)
        with patch("r2lab_api.routers.registrations.send_mail"):
            r = client.post(
                "/registrations/1/approve",
                json={"slice_name": "inria_test"},
                headers=auth(admin_token),
            )
        user_id = r.json()["id"]
        # check the slice exists with the user as member
        slices = client.get("/slices", headers=auth(admin_token)).json()
        matching = [s for s in slices if s["name"] == "inria_test"]
        assert len(matching) == 1
        assert user_id in matching[0]["member_ids"]

    def test_approve_without_slice(self, client, db, admin_token):
        self._pending_admin_reg(client, db)
        with patch("r2lab_api.routers.registrations.send_mail"):
            r = client.post(
                "/registrations/1/approve",
                json={},
                headers=auth(admin_token),
            )
        assert r.status_code == 200

    def test_approve_sends_password_setup_email(
        self, client, db, admin_token,
    ):
        self._pending_admin_reg(client, db)
        with patch("r2lab_api.routers.registrations.send_mail") as mock_mail:
            client.post(
                "/registrations/1/approve",
                json={},
                headers=auth(admin_token),
            )
        mock_mail.assert_called_once()
        assert "set-password" in mock_mail.call_args.kwargs["body"]

    def test_approve_non_pending_rejected(self, client, db, admin_token):
        """Can't approve a request that is still pending_email."""
        _submit(client)  # status = pending_email
        with patch("r2lab_api.routers.registrations.send_mail"):
            r = client.post(
                "/registrations/1/approve",
                json={},
                headers=auth(admin_token),
            )
        assert r.status_code == 400

    def test_approve_sets_registration_status(
        self, client, db, admin_token,
    ):
        self._pending_admin_reg(client, db)
        with patch("r2lab_api.routers.registrations.send_mail"):
            client.post(
                "/registrations/1/approve",
                json={"comment": "Welcome!"},
                headers=auth(admin_token),
            )
        reg = client.get(
            "/registrations/1", headers=auth(admin_token),
        ).json()
        assert reg["status"] == "approved"
        assert reg["decided_at"] is not None
        assert reg["admin_comment"] == "Welcome!"


# ---------- Reject ----------

class TestReject:

    def _pending_admin_reg(self, client, db):
        _, mock_mail = _submit(client)
        token = _extract_token_from_mail(mock_mail)
        with patch("r2lab_api.routers.registrations.send_mail"):
            client.post("/registrations/verify", json={"token": token})

    def test_reject_sets_status(self, client, db, admin_token):
        self._pending_admin_reg(client, db)
        with patch("r2lab_api.routers.registrations.send_mail"):
            r = client.post(
                "/registrations/1/reject",
                json={"comment": "No capacity"},
                headers=auth(admin_token),
            )
        assert r.status_code == 204
        reg = client.get(
            "/registrations/1", headers=auth(admin_token),
        ).json()
        assert reg["status"] == "rejected"
        assert reg["admin_comment"] == "No capacity"

    def test_reject_does_not_send_email(self, client, db, admin_token):
        self._pending_admin_reg(client, db)
        with patch("r2lab_api.routers.registrations.send_mail") as mock_mail:
            client.post(
                "/registrations/1/reject",
                json={"comment": "No capacity"},
                headers=auth(admin_token),
            )
        mock_mail.assert_not_called()

    def test_reject_non_pending_rejected(self, client, db, admin_token):
        _submit(client)  # status = pending_email
        with patch("r2lab_api.routers.registrations.send_mail"):
            r = client.post(
                "/registrations/1/reject",
                json={},
                headers=auth(admin_token),
            )
        assert r.status_code == 400


# ---------- Set password ----------

class TestSetPassword:

    def _approved_user_token(self, client, db, admin_token):
        """Go through the full flow and return the raw password-setup token."""
        _, mock_mail = _submit(client)
        verify_token = _extract_token_from_mail(mock_mail)
        with patch("r2lab_api.routers.registrations.send_mail"):
            client.post("/registrations/verify",
                        json={"token": verify_token})
        with patch("r2lab_api.routers.registrations.send_mail") as approve_mail:
            client.post(
                "/registrations/1/approve",
                json={},
                headers=auth(admin_token),
            )
        body = approve_mail.call_args.kwargs["body"]
        for line in body.splitlines():
            if "token=" in line:
                return line.strip().split("token=")[1]
        raise ValueError("No token in approval email")

    def test_set_password_and_login(self, client, db, admin_token):
        pwd_token = self._approved_user_token(client, db, admin_token)
        r = client.post("/auth/set-password", json={
            "token": pwd_token,
            "password": "my-secret-123",
        })
        assert r.status_code == 200
        # now login should work
        r = client.post("/auth/login", json={
            "email": REG_DATA["email"],
            "password": "my-secret-123",
        })
        assert r.status_code == 200
        assert "access_token" in r.json()

    def test_set_password_invalid_token(self, client, db):
        r = client.post("/auth/set-password", json={
            "token": "not-a-real-token",
            "password": "whatever",
        })
        assert r.status_code == 400

    def test_set_password_token_single_use(self, client, db, admin_token):
        pwd_token = self._approved_user_token(client, db, admin_token)
        client.post("/auth/set-password", json={
            "token": pwd_token,
            "password": "first-password",
        })
        r = client.post("/auth/set-password", json={
            "token": pwd_token,
            "password": "second-password",
        })
        assert r.status_code == 400


# ---------- Forgot password ----------

class TestForgotPassword:

    def test_forgot_password_always_200(self, client, db):
        """Returns 200 even for non-existent emails (no enumeration)."""
        with patch("r2lab_api.routers.auth.send_mail"):
            r = client.post("/auth/forgot-password", json={
                "email": "nobody@example.com",
            })
        assert r.status_code == 200

    def test_forgot_password_sends_email_for_existing_user(
        self, client, db,
    ):
        user = _make_user(db, email="real@example.com")
        with patch("r2lab_api.routers.auth.send_mail") as mock_mail:
            r = client.post("/auth/forgot-password", json={
                "email": "real@example.com",
            })
        assert r.status_code == 200
        mock_mail.assert_called_once()
        assert "set-password" in mock_mail.call_args.kwargs["body"]

    def test_forgot_password_token_works(self, client, db):
        _make_user(db, email="real@example.com")
        with patch("r2lab_api.routers.auth.send_mail") as mock_mail:
            client.post("/auth/forgot-password", json={
                "email": "real@example.com",
            })
        body = mock_mail.call_args.kwargs["body"]
        token = None
        for line in body.splitlines():
            if "token=" in line:
                token = line.strip().split("token=")[1]
        assert token is not None
        r = client.post("/auth/set-password", json={
            "token": token,
            "password": "new-password-123",
        })
        assert r.status_code == 200
        # login with new password
        r = client.post("/auth/login", json={
            "email": "real@example.com",
            "password": "new-password-123",
        })
        assert r.status_code == 200
