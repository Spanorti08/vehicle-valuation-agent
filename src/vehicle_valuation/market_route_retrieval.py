import json
from pathlib import Path

from vehicle_valuation.model import MarketSearchRoute


def load_market_search_routes(
    path: Path,
) -> list[MarketSearchRoute]:
    """加载并验证市场车系搜索路由。"""

    data = json.loads(
        path.read_text(encoding="utf-8")
    )

    return [
        MarketSearchRoute.model_validate(item)
        for item in data
    ]


def retrieve_market_search_route(
    routes: list[MarketSearchRoute],
    provider: str,
    market_series: str,
) -> MarketSearchRoute | None:
    """查找指定平台和市场车系对应的搜索路由。"""

    for route in routes:
        if (
            route.provider == provider
            and route.market_series == market_series
        ):
            return route

    return None