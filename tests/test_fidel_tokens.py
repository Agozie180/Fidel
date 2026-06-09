from backend.config import Settings
from backend.tokens import TokenRegistry, ELIGIBLE_TOKENS, ELIGIBLE_TOKEN_SYMBOLS


def test_live_registry_requires_contract_address(tmp_path):
    cfg = Settings(eligible_token_registry_path=tmp_path / "missing.json")
    registry = TokenRegistry(cfg)
    try:
        registry.validate("CAKE", require_contract=True)
    except ValueError as exc:
        assert "no BSC contract address" in str(exc)
    else:
        raise AssertionError("live registry accepted a symbol without a BSC contract")


def test_external_registry_loads_verified_contract(tmp_path):
    path = tmp_path / "tokens.json"
    path.write_text('{"tokens":[{"symbol":"CAKE","address":"0x0e09fabb73bd3ade0a17ecc321fd13a19e81ce82","decimals":18}]}', encoding="utf-8")
    registry = TokenRegistry(Settings(eligible_token_registry_path=path))
    token = registry.validate("CAKE", require_contract=True)
    assert token.address == "0x0e09fabb73bd3ade0a17ecc321fd13a19e81ce82"
    assert registry.status()["contract_ready"] == 1


def test_full_dorahacks_seed_list_is_loaded():
    assert len(ELIGIBLE_TOKEN_SYMBOLS) == 149
    assert len(ELIGIBLE_TOKENS) == 148
    for symbol in ["USDe", "M", "XAUt", "币安人生", "BabyDoge", "lisUSD", "XAUM"]:
        assert symbol in ELIGIBLE_TOKENS


def test_case_distinct_symbols_are_preserved():
    registry = TokenRegistry()
    assert registry.validate("USDf").symbol == "USDf"
    assert registry.validate("USDF").symbol == "USDF"
