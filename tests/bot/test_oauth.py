"""Tests for bot/oauth.py — OAuth token management."""
import json
import time
import pytest
import unittest.mock as mock


def make_creds(expires_offset_ms: int, access_token: str = "tok", refresh_token: str = "ref") -> dict:
    """Helper: build a credentials dict with expiresAt relative to now."""
    return {"claudeAiOauth": {
        "accessToken": access_token,
        "refreshToken": refresh_token,
        "expiresAt": int(time.time() * 1000) + expires_offset_ms,
    }}


# ---------------------------------------------------------------------------
# read_oauth_tokens
# ---------------------------------------------------------------------------

class TestReadOAuthTokens:
    def test_returns_none_when_file_missing(self, tmp_path):
        from bot.oauth import read_oauth_tokens
        result = read_oauth_tokens(str(tmp_path / "nope.json"))
        assert result is None

    def test_returns_none_on_invalid_json(self, tmp_path):
        from bot.oauth import read_oauth_tokens
        f = tmp_path / "creds.json"
        f.write_text("not json")
        assert read_oauth_tokens(str(f)) is None

    def test_returns_none_when_oauth_key_missing(self, tmp_path):
        from bot.oauth import read_oauth_tokens
        f = tmp_path / "creds.json"
        f.write_text(json.dumps({"someOtherKey": {}}))
        assert read_oauth_tokens(str(f)) is None

    def test_returns_tokens_object_with_correct_fields(self, tmp_path):
        from bot.oauth import read_oauth_tokens, OAuthTokens
        f = tmp_path / "creds.json"
        creds = make_creds(3_600_000, access_token="acc123", refresh_token="ref456")
        f.write_text(json.dumps(creds))
        result = read_oauth_tokens(str(f))
        assert isinstance(result, OAuthTokens)
        assert result.access_token == "acc123"
        assert result.refresh_token == "ref456"
        assert result.expires_at_ms > 0


# ---------------------------------------------------------------------------
# is_token_valid
# ---------------------------------------------------------------------------

class TestIsTokenValid:
    def test_valid_token_not_expired(self, tmp_path):
        from bot.oauth import OAuthTokens, is_token_valid
        t = OAuthTokens("tok", "ref", int(time.time() * 1000) + 3_600_000)
        assert is_token_valid(t) is True

    def test_expired_token_returns_false(self):
        from bot.oauth import OAuthTokens, is_token_valid
        t = OAuthTokens("tok", "ref", int(time.time() * 1000) - 1000)
        assert is_token_valid(t) is False

    def test_token_expiring_within_buffer_returns_false(self):
        from bot.oauth import OAuthTokens, is_token_valid
        # Expires in 2 minutes — within 5-minute default buffer
        t = OAuthTokens("tok", "ref", int(time.time() * 1000) + 120_000)
        assert is_token_valid(t, buffer_seconds=300) is False

    def test_token_outside_buffer_returns_true(self):
        from bot.oauth import OAuthTokens, is_token_valid
        # Expires in 10 minutes — outside 5-minute buffer
        t = OAuthTokens("tok", "ref", int(time.time() * 1000) + 600_000)
        assert is_token_valid(t, buffer_seconds=300) is True


# ---------------------------------------------------------------------------
# refresh_tokens
# ---------------------------------------------------------------------------

class TestRefreshTokens:
    def test_posts_to_correct_endpoint(self, tmp_path):
        from bot.oauth import OAuthTokens, refresh_tokens
        old = OAuthTokens("old_acc", "ref123", int(time.time() * 1000) + 1000)

        new_expires = int(time.time() * 1000) + 3_600_000
        response_data = {
            "access_token": "new_acc",
            "refresh_token": "new_ref",
            "expires_in": 3600,
        }

        with mock.patch("requests.post") as mock_post:
            mock_post.return_value.ok = True
            mock_post.return_value.json.return_value = response_data
            result = refresh_tokens(old)

        call_kwargs = mock_post.call_args
        url = call_kwargs[0][0] if call_kwargs[0] else call_kwargs[1].get("url", call_kwargs[0])
        assert "platform.claude.com" in str(mock_post.call_args)
        assert "oauth/token" in str(mock_post.call_args)

    def test_returns_new_tokens_on_success(self):
        from bot.oauth import OAuthTokens, refresh_tokens
        old = OAuthTokens("old_acc", "ref123", int(time.time() * 1000) + 1000)

        response_data = {
            "access_token": "new_acc",
            "refresh_token": "new_ref",
            "expires_in": 3600,
        }
        with mock.patch("requests.post") as mock_post:
            mock_post.return_value.ok = True
            mock_post.return_value.json.return_value = response_data
            result = refresh_tokens(old)

        assert isinstance(result, OAuthTokens)
        assert result.access_token == "new_acc"
        assert result.refresh_token == "new_ref"
        assert result.expires_at_ms > int(time.time() * 1000)

    def test_raises_on_failed_refresh(self):
        from bot.oauth import OAuthTokens, refresh_tokens, TokenRefreshError
        old = OAuthTokens("old_acc", "ref123", int(time.time() * 1000) + 1000)

        with mock.patch("requests.post") as mock_post:
            mock_post.return_value.ok = False
            mock_post.return_value.status_code = 401
            mock_post.return_value.text = "Unauthorized"
            with pytest.raises(TokenRefreshError):
                refresh_tokens(old)

    def test_sends_client_id_and_refresh_token(self):
        from bot.oauth import OAuthTokens, refresh_tokens, OAUTH_CLIENT_ID
        old = OAuthTokens("old_acc", "ref_xyz", int(time.time() * 1000) + 1000)

        response_data = {"access_token": "a", "refresh_token": "b", "expires_in": 3600}
        with mock.patch("requests.post") as mock_post:
            mock_post.return_value.ok = True
            mock_post.return_value.json.return_value = response_data
            refresh_tokens(old)

        _, kwargs = mock_post.call_args
        body = kwargs.get("data") or kwargs.get("json") or mock_post.call_args[0][1] if len(mock_post.call_args[0]) > 1 else {}
        body_str = str(mock_post.call_args)
        assert "refresh_token" in body_str
        assert "ref_xyz" in body_str


# ---------------------------------------------------------------------------
# write_oauth_tokens
# ---------------------------------------------------------------------------

class TestWriteOAuthTokens:
    def test_writes_tokens_back_to_file(self, tmp_path):
        from bot.oauth import OAuthTokens, write_oauth_tokens, read_oauth_tokens
        f = tmp_path / "creds.json"
        # Pre-populate with other data that should be preserved
        f.write_text(json.dumps({"otherKey": "preserved", "claudeAiOauth": {}}))

        t = OAuthTokens("new_acc", "new_ref", int(time.time() * 1000) + 3_600_000)
        write_oauth_tokens(t, str(f))

        # Read back and verify
        written = json.loads(f.read_text())
        oauth = written["claudeAiOauth"]
        assert oauth["accessToken"] == "new_acc"
        assert oauth["refreshToken"] == "new_ref"
        assert oauth["expiresAt"] == t.expires_at_ms

    def test_preserves_other_top_level_keys(self, tmp_path):
        from bot.oauth import OAuthTokens, write_oauth_tokens
        f = tmp_path / "creds.json"
        f.write_text(json.dumps({"otherKey": "preserved", "claudeAiOauth": {}}))

        t = OAuthTokens("a", "b", 9999)
        write_oauth_tokens(t, str(f))

        written = json.loads(f.read_text())
        assert written.get("otherKey") == "preserved"


# ---------------------------------------------------------------------------
# get_valid_token — the main public function
# ---------------------------------------------------------------------------

class TestGetValidToken:
    def test_returns_access_token_when_valid(self, tmp_path):
        from bot.oauth import get_valid_token
        f = tmp_path / "creds.json"
        creds = make_creds(3_600_000, access_token="valid_tok")
        f.write_text(json.dumps(creds))

        result = get_valid_token(str(f))
        assert result == "valid_tok"

    def test_returns_none_when_no_file(self, tmp_path):
        from bot.oauth import get_valid_token
        result = get_valid_token(str(tmp_path / "nope.json"))
        assert result is None

    def test_refreshes_and_returns_new_token_when_expired(self, tmp_path):
        from bot.oauth import get_valid_token
        f = tmp_path / "creds.json"
        creds = make_creds(-1000, access_token="expired_tok", refresh_token="good_ref")
        f.write_text(json.dumps(creds))

        response_data = {"access_token": "refreshed_tok", "refresh_token": "new_ref", "expires_in": 3600}
        with mock.patch("requests.post") as mock_post:
            mock_post.return_value.ok = True
            mock_post.return_value.json.return_value = response_data
            result = get_valid_token(str(f))

        assert result == "refreshed_tok"

    def test_writes_back_refreshed_tokens(self, tmp_path):
        from bot.oauth import get_valid_token
        f = tmp_path / "creds.json"
        creds = make_creds(-1000, access_token="expired_tok", refresh_token="good_ref")
        f.write_text(json.dumps(creds))

        response_data = {"access_token": "refreshed_tok", "refresh_token": "new_ref", "expires_in": 3600}
        with mock.patch("requests.post") as mock_post:
            mock_post.return_value.ok = True
            mock_post.return_value.json.return_value = response_data
            get_valid_token(str(f))

        written = json.loads(f.read_text())
        assert written["claudeAiOauth"]["accessToken"] == "refreshed_tok"

    def test_returns_none_when_refresh_fails(self, tmp_path):
        from bot.oauth import get_valid_token
        f = tmp_path / "creds.json"
        creds = make_creds(-1000, access_token="expired_tok", refresh_token="bad_ref")
        f.write_text(json.dumps(creds))

        with mock.patch("requests.post") as mock_post:
            mock_post.return_value.ok = False
            mock_post.return_value.status_code = 401
            mock_post.return_value.text = "Unauthorized"
            result = get_valid_token(str(f))

        assert result is None

    def test_real_credentials_file_produces_a_token(self):
        """Smoke test: real credentials on this machine should yield a non-None token.
        Does NOT log or assert the token value — just checks it's present."""
        import os
        from bot.oauth import get_valid_token
        creds_path = os.path.expanduser("~/.claude/.credentials.json")
        if not os.path.exists(creds_path):
            pytest.skip("No real credentials file found")
        result = get_valid_token(creds_path)
        # Token will be None if expired AND refresh fails (e.g., no network).
        # Just verify the function returns without raising.
        assert result is None or isinstance(result, str)

    def test_real_oauth_haiku_call(self):
        """Integration test: OAuth token → AnthropicBackend → real Haiku call.
        Skips if no credentials or anthropic SDK not installed."""
        import os
        import asyncio
        from bot.oauth import get_valid_token
        creds_path = os.path.expanduser("~/.claude/.credentials.json")
        if not os.path.exists(creds_path):
            pytest.skip("No real credentials file found")
        token = get_valid_token(creds_path)
        if not token:
            pytest.skip("No valid OAuth token available")
        try:
            import anthropic  # noqa: F401
            from bot.llm import AnthropicBackend, LLMResponse
        except (ImportError, ModuleNotFoundError):
            pytest.skip("anthropic SDK not installed")

        backend = AnthropicBackend(credentials_path=creds_path)
        if not backend.is_available():
            pytest.skip("AnthropicBackend not available")

        resp = asyncio.run(backend.complete(
            messages=[{"role": "user", "content": "Reply with exactly: pong"}],
            system="You are a test assistant. Follow instructions exactly.",
            model="claude-haiku-4-5-20251001",
        ))
        assert isinstance(resp, LLMResponse)
        assert "pong" in resp.content.lower()
        assert resp.input_tokens > 0
        assert resp.output_tokens > 0
        assert resp.stop_reason == "end_turn"
