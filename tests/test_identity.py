from app.identity import map_auth0_claims, normalize_user_id

KNOWN = {"alice", "bob", "dave", "carol", "eve", "frank", "nina"}


def test_explicit_claim_and_directory_email():
    assert normalize_user_id("User:Alice") == "alice"
    assert map_auth0_claims({"fga_user": "user:bob"}, KNOWN) == "bob"
    assert map_auth0_claims({"email": "alice@northline.example"}, KNOWN) == "alice"
    assert map_auth0_claims({"nickname": "Dave"}, KNOWN) == "dave"


def test_display_name_and_subject_do_not_become_a_manager():
    mapped = map_auth0_claims(
        {"name": "Alice Chen", "sub": "auth0|alice", "email": "visitor@example.com"},
        KNOWN,
    )
    assert mapped != "alice"
    assert mapped.startswith("auth0_")
    stranger = map_auth0_claims({"sub": "google-oauth2|999"}, KNOWN)
    assert stranger not in KNOWN
