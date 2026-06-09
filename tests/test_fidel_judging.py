from backend.config import Settings
from backend.judging import build_judging_readiness


def test_judging_readiness_scores_core_sponsor_stack():
    cfg = Settings(
        cmc_api_key="cmc",
        twak_command="twak",
        bnb_agent_sdk_command="bnb-agent",
        openai_api_key="openai",
        autonomous_live=True,
    )
    readiness = build_judging_readiness(
        cfg=cfg,
        registry_status={"contract_ready": 10},
        trade_count=3,
        today_trades=1,
        has_bsc_hashes=True,
    )
    assert readiness.score >= 90
    assert readiness.grade == "MYTHIC READY"


def test_judging_readiness_names_missing_items():
    readiness = build_judging_readiness(
        cfg=Settings(cmc_api_key="", cmc_mcp_command="", bnb_agent_sdk_command="", openai_api_key="", anthropic_api_key=""),
        registry_status={"contract_ready": 0},
        trade_count=0,
        today_trades=0,
        has_bsc_hashes=False,
    )
    assert "CMC Agent Hub + x402" in readiness.missing
    assert "Strict BSC token registry" in readiness.missing

