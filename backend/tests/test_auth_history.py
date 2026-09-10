import uuid

from fastapi.testclient import TestClient

from app.core.database import SessionLocal
from app.main import app
from app.models.account import User


def account_payload(prefix: str) -> dict[str, str]:
    suffix = uuid.uuid4().hex[:10]
    return {
        "username": f"{prefix}_{suffix}",
        "email": f"{prefix}.{suffix}@example.com",
        "phone_number": "+1 202 555 0147",
        "password": "CorrectHorse42!",
        "password_confirmation": "CorrectHorse42!",
    }


def signup(client: TestClient, prefix: str) -> dict:
    payload = account_payload(prefix)
    response = client.post("/api/v1/auth/signup", json=payload)
    assert response.status_code == 201, response.text
    return {**payload, "id": response.json()["user"]["id"]}


def login(client: TestClient, account: dict) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"identifier": account["email"], "password": account["password"]},
    )
    assert response.status_code == 200, response.text
    assert response.cookies.get("archai_session")


def workspace_payload(title: str) -> dict:
    return {
        "title": title,
        "description": (
            "Build an EV charging station booking platform with station discovery, "
            "live charger availability, bookings, payments, and operator controls."
        ),
        "business_context": "Create an auditable architecture plan.",
        "preferred_cloud": "No preference",
        "constraints": [],
    }


def test_signup_validation_duplicates_login_profile_and_logout(client: TestClient) -> None:
    anonymous_session = client.get("/api/v1/auth/session")
    assert anonymous_session.status_code == 200
    assert anonymous_session.json() == {"authenticated": False, "user": None}

    account = account_payload("account")
    signup_response = client.post("/api/v1/auth/signup", json=account)
    assert signup_response.status_code == 201
    public_user = signup_response.json()["user"]
    assert public_user["username"] == account["username"]
    assert public_user["email"] == account["email"]
    assert "password" not in signup_response.text

    with SessionLocal() as db:
        stored_user = db.get(User, public_user["id"])
        assert stored_user is not None
        assert stored_user.password_hash != account["password"]
        assert stored_user.password_hash.startswith("$argon2")

    duplicate_username = {**account, "email": f"other.{uuid.uuid4().hex}@example.com"}
    assert client.post("/api/v1/auth/signup", json=duplicate_username).status_code == 409

    duplicate_email = {**account, "username": f"other_{uuid.uuid4().hex[:10]}"}
    assert client.post("/api/v1/auth/signup", json=duplicate_email).status_code == 409

    mismatched = {
        **account_payload("mismatch"),
        "password_confirmation": "DifferentPassword42!",
    }
    assert client.post("/api/v1/auth/signup", json=mismatched).status_code == 422

    invalid_email = {**account_payload("invalid"), "email": "not-an-email"}
    assert client.post("/api/v1/auth/signup", json=invalid_email).status_code == 422

    wrong_password = client.post(
        "/api/v1/auth/login",
        json={"identifier": account["username"], "password": "wrong-password"},
    )
    assert wrong_password.status_code == 401

    login(client, account)
    me_response = client.get("/api/v1/auth/me")
    assert me_response.status_code == 200
    assert me_response.json()["user"]["id"] == public_user["id"]
    authenticated_session = client.get("/api/v1/auth/session")
    assert authenticated_session.status_code == 200
    assert authenticated_session.json()["authenticated"] is True
    assert authenticated_session.json()["user"]["id"] == public_user["id"]

    profile_response = client.patch(
        "/api/v1/auth/profile", json={"phone_number": "+44 20 7946 0958"}
    )
    assert profile_response.status_code == 200
    assert profile_response.json()["user"]["phone_number"] == "+44 20 7946 0958"

    logout_response = client.post("/api/v1/auth/logout")
    assert logout_response.status_code == 204
    clear_cookie = logout_response.headers["set-cookie"].casefold()
    assert "max-age=0" in clear_cookie
    assert "httponly" in clear_cookie
    assert "samesite=lax" in clear_cookie
    assert client.get("/api/v1/auth/me").status_code == 401


def test_private_history_sharing_read_only_and_revocation() -> None:
    with (
        TestClient(app) as owner_client,
        TestClient(app) as recipient_client,
        TestClient(app) as unrelated_client,
    ):
        owner = signup(owner_client, "owner")
        recipient = signup(recipient_client, "recipient")
        unrelated = signup(unrelated_client, "unrelated")
        login(owner_client, owner)
        login(recipient_client, recipient)
        login(unrelated_client, unrelated)

        create_response = owner_client.post(
            "/api/v1/workspaces",
            json=workspace_payload(f"Private Architecture {uuid.uuid4().hex[:8]}"),
        )
        assert create_response.status_code == 201, create_response.text
        workspace_id = create_response.json()["id"]

        owner_history = owner_client.get("/api/v1/history")
        assert owner_history.status_code == 200
        conversation = next(
            item for item in owner_history.json() if item["workspace_id"] == workspace_id
        )
        conversation_id = conversation["id"]
        assert conversation["permission"] == "OWNER"

        detail = owner_client.get(f"/api/v1/history/{conversation_id}")
        assert detail.status_code == 200
        assert [message["role"] for message in detail.json()["messages"]] == [
            "user",
            "assistant",
        ]

        change_response = owner_client.post(
            f"/api/v1/workspaces/{workspace_id}/changes",
            json={"change_request": "Add mobile clients to the first release."},
        )
        assert change_response.status_code == 200
        updated_detail = owner_client.get(f"/api/v1/history/{conversation_id}").json()
        assert len(updated_detail["messages"]) == 4
        assert updated_detail["messages"][-2]["content"].startswith("Add mobile")

        assert recipient_client.get(f"/api/v1/workspaces/{workspace_id}").status_code == 404
        assert unrelated_client.get(f"/api/v1/workspaces/{workspace_id}").status_code == 404
        assert all(
            item["workspace_id"] != workspace_id
            for item in recipient_client.get("/api/v1/history").json()
        )

        username_search = owner_client.get(
            "/api/v1/users/search", params={"q": recipient["username"]}
        )
        assert username_search.status_code == 200
        assert any(item["id"] == recipient["id"] for item in username_search.json())
        email_search = owner_client.get(
            "/api/v1/users/search", params={"q": recipient["email"]}
        )
        assert any(item["id"] == recipient["id"] for item in email_search.json())

        share_response = owner_client.post(
            f"/api/v1/history/{conversation_id}/shares",
            json={"recipient_id": recipient["id"], "permission": "VIEW"},
        )
        assert share_response.status_code == 201, share_response.text

        recipient_history = recipient_client.get("/api/v1/history").json()
        shared = next(item for item in recipient_history if item["id"] == conversation_id)
        assert shared["permission"] == "VIEW"
        assert shared["owner"]["id"] == owner["id"]
        assert recipient_client.get(f"/api/v1/history/{conversation_id}").status_code == 200
        assert recipient_client.get(f"/api/v1/workspaces/{workspace_id}").status_code == 200

        assert (
            recipient_client.patch(
                f"/api/v1/history/{conversation_id}", json={"title": "Not allowed"}
            ).status_code
            == 403
        )
        assert recipient_client.delete(f"/api/v1/history/{conversation_id}").status_code == 403
        assert (
            recipient_client.post(
                f"/api/v1/workspaces/{workspace_id}/changes",
                json={"change_request": "Recipient must not edit this."},
            ).status_code
            == 403
        )
        assert unrelated_client.get(f"/api/v1/history/{conversation_id}").status_code == 404
        assert unrelated_client.get(f"/api/v1/workspaces/{workspace_id}").status_code == 404

        revoke_response = owner_client.delete(
            f"/api/v1/history/{conversation_id}/shares/{recipient['id']}"
        )
        assert revoke_response.status_code == 204
        assert recipient_client.get(f"/api/v1/history/{conversation_id}").status_code == 404
        assert recipient_client.get(f"/api/v1/workspaces/{workspace_id}").status_code == 404
