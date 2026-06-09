from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .config import Settings, settings


ELIGIBLE_TOKEN_SYMBOLS: tuple[str, ...] = (
    "ETH", "USDT", "USDC", "XRP", "TRX", "DOGE", "ZEC", "ADA", "LINK", "BCH", "DAI", "TON", "USD1",
    "USDe", "M", "LTC", "AVAX", "SHIB", "XAUt", "WLFI", "H", "DOT", "UNI", "ASTER", "DEXE", "USDD",
    "ETC", "AAVE", "ATOM", "U", "STABLE", "FIL", "INJ", "币安人生", "NIGHT", "FET", "TUSD", "BONK",
    "PENGU", "CAKE", "SIREN", "LUNC", "ZRO", "KITE", "FDUSD", "BEAT", "PIEVERSE", "BTT", "NFT",
    "EDGE", "FLOKI", "LDO", "B", "FF", "PENDLE", "NEX", "STG", "AXS", "TWT", "HOME", "RAY", "COMP",
    "GWEI", "XCN", "GENIUS", "XPL", "BAT", "SKYAI", "APE", "IP", "SFP", "TAG", "NXPC", "AB", "SAHARA",
    "1INCH", "CHEEMS", "BANANAS31", "RIVER", "MYX", "RAVE", "SNX", "FORM", "LAB", "HTX", "USDf",
    "CTM", "BDX", "SLX", "UB", "DUCKY", "FRAX", "BILL", "WFI", "KOGE", "ALE", "FRXUSD", "USDF",
    "GOMINING", "VCNT", "GUA", "DUSD", "SMILEK", "0G", "BEAM", "MY", "SLX", "SOON", "REAL", "Q", "AIOZ",
    "ZIG", "YFI", "TAC", "lisUSD", "CYS", "ZAMA", "TRIA", "HUMA", "PLUME", "ZIL", "XPR", "ZETA",
    "BabyDoge", "NILA", "ROSE", "VELO", "UAI", "BRETT", "OPEN", "BSB", "TOSHI", "BAS", "ACH", "AXL",
    "LUR", "ELF", "KAVA", "APR", "IRYS", "EURI", "XUSD", "BARD", "DUSK", "SUSHI", "PEAQ", "COAI",
    "BDCA", "XAUM",
)
ELIGIBLE_TOKENS: set[str] = set(ELIGIBLE_TOKEN_SYMBOLS)
DISPLAY_SYMBOLS: dict[str, str] = {symbol: symbol for symbol in ELIGIBLE_TOKEN_SYMBOLS}
SYMBOL_ALIASES: dict[str, str] = {}
for symbol in ELIGIBLE_TOKEN_SYMBOLS:
    SYMBOL_ALIASES.setdefault(symbol.upper(), symbol)


@dataclass(frozen=True)
class TokenMeta:
    symbol: str
    address: str = ""
    decimals: int = 18
    source: str = "seed"


class TokenRegistry:
    def __init__(self, cfg: Settings = settings) -> None:
        self.cfg = cfg
        self.tokens = {symbol: TokenMeta(symbol=symbol) for symbol in sorted(ELIGIBLE_TOKENS, key=str.upper)}
        self.loaded_external_registry = False
        self._load_external(cfg.eligible_token_registry_path)

    def _load_external(self, path: Path) -> None:
        if not path.exists():
            return
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows = payload.get("tokens", payload if isinstance(payload, list) else [])
        loaded: dict[str, TokenMeta] = {}
        for row in rows:
            symbol = self._canonical(str(row["symbol"]).strip())
            if symbol not in ELIGIBLE_TOKENS:
                raise ValueError(f"{symbol} in external registry is not in the competition seed allowlist")
            loaded[symbol] = TokenMeta(
                symbol=DISPLAY_SYMBOLS.get(symbol, symbol),
                address=str(row.get("address", "")).lower(),
                decimals=int(row.get("decimals", 18)),
                source=str(row.get("source", path.name)),
            )
        self.tokens.update(loaded)
        self.loaded_external_registry = True

    def validate(self, symbol: str, *, address: str = "", require_contract: bool = False) -> TokenMeta:
        normalized = self._canonical(symbol)
        token = self.tokens.get(normalized)
        if not token:
            raise ValueError(f"{normalized} is not on Fidel's eligible-token allowlist")
        if address and token.address and token.address != address.lower():
            raise ValueError(f"{normalized} contract address does not match the registered BSC token")
        if require_contract and not token.address:
            raise ValueError(f"{normalized} has no BSC contract address in the live eligible-token registry")
        return token

    def status(self) -> dict:
        contract_ready = sum(1 for token in self.tokens.values() if token.address)
        return {
            "seed_symbols": len(ELIGIBLE_TOKENS),
            "official_list_entries": len(ELIGIBLE_TOKEN_SYMBOLS),
            "registry_symbols": len(self.tokens),
            "contract_ready": contract_ready,
            "external_registry_loaded": self.loaded_external_registry,
            "strict_live_contracts": self.cfg.strict_live_token_contracts,
            "registry_path": str(self.cfg.eligible_token_registry_path),
        }

    def _canonical(self, symbol: str) -> str:
        raw = symbol.strip().replace("BSC-", "")
        if raw in ELIGIBLE_TOKENS:
            return raw
        return SYMBOL_ALIASES.get(raw.upper(), raw.upper())


registry = TokenRegistry()


def validate_token(symbol: str, *, address: str = "", require_contract: bool = False) -> str:
    return registry.validate(symbol, address=address, require_contract=require_contract).symbol
