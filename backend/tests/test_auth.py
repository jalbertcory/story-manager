"""Tests for authentication: token generation, hashing, prefix extraction."""

from backend.app.auth import generate_reader_token, hash_token, _extract_prefix


class TestGenerateReaderToken:
    def test_token_format(self):
        token, prefix = generate_reader_token()
        assert token.startswith("smr_")
        assert prefix.startswith("smr_")
        assert token.startswith(prefix)
        # Token should have three parts: smr, hex prefix, secret
        parts = token.split("_", 2)
        assert len(parts) == 3
        assert parts[0] == "smr"

    def test_tokens_are_unique(self):
        tokens = set()
        for _ in range(50):
            token, _ = generate_reader_token()
            tokens.add(token)
        assert len(tokens) == 50

    def test_prefix_is_stable(self):
        token, prefix = generate_reader_token()
        extracted = _extract_prefix(token)
        assert extracted == prefix


class TestHashToken:
    def test_deterministic(self):
        assert hash_token("test123") == hash_token("test123")

    def test_different_tokens_different_hashes(self):
        assert hash_token("token_a") != hash_token("token_b")

    def test_returns_hex_string(self):
        h = hash_token("test")
        assert len(h) == 64  # SHA256 hex digest
        assert all(c in "0123456789abcdef" for c in h)


class TestExtractPrefix:
    def test_valid_token(self):
        assert _extract_prefix("smr_abcd1234_secret") == "smr_abcd1234"

    def test_invalid_prefix(self):
        assert _extract_prefix("invalid_token") is None

    def test_wrong_scheme(self):
        assert _extract_prefix("xyz_abcd_secret") is None

    def test_too_few_parts(self):
        assert _extract_prefix("smr_only") is None

    def test_empty_string(self):
        assert _extract_prefix("") is None
