import re
from decimal import Decimal
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from vehicle_valuation.model import (
    MarketListing,
    MarketListingDetail,
)
from playwright.sync_api import sync_playwright


def fetch_market_page(
    url: str,
    scroll_rounds: int = 0,
) -> str:
    """使用本机Chrome下载页面，并按需滚动加载更多车源。"""

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            channel="chrome",
            headless=True,
        )

        page = browser.new_page(
            locale="zh-CN",
        )

        try:
            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=30_000,
            )

            page.wait_for_timeout(3_000)

            for _ in range(scroll_rounds):
                page.mouse.wheel(0, 5_000)
                page.wait_for_timeout(1_000)

            html = page.content()

        finally:
            browser.close()

    return html


def capture_market_listing_screenshots(
    url: str,
) -> tuple[bytes, bytes]:
    """截取车辆顶部信息和车况详情两张网页截图。"""

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            channel="chrome",
            headless=True,
        )

        page = browser.new_page(
            locale="zh-CN",
            viewport={
                "width": 1600,
                "height": 900,
            },
        )

        try:
            page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=30_000,
            )
            page.wait_for_timeout(3_000)

            body_text = page.locator(
                "body"
            ).inner_text()

            verification_words = [
                "尝试太多了",
                "网络错误",
                "Security Verification",
                "验证连接安全性",
            ]

            if any(
                word in body_text
                for word in verification_words
            ):
                raise ValueError(
                    "网页触发访问验证，无法截图"
                )

            page.evaluate(
                "window.scrollTo(0, 0)"
            )
            page.wait_for_timeout(1_000)

            vehicle_screenshot = (
                page.screenshot(
                    type="png",
                    full_page=False,
                )
            )

            detail_anchor = page.get_by_text(
                "档案手续",
                exact=True,
            )

            if detail_anchor.count() > 0:
                detail_anchor.first.evaluate(
                    """
                    element => {
                        const top =
                            element.getBoundingClientRect().top
                            + window.scrollY
                            - 220;

                        window.scrollTo({
                            top: Math.max(0, top),
                            behavior: "instant"
                        });
                    }
                    """
                )
            else:
                page.evaluate(
                    "window.scrollTo(0, 800)"
                )

            page.wait_for_timeout(1_000)

            detail_screenshot = (
                page.screenshot(
                    type="png",
                    full_page=False,
                )
            )

        finally:
            browser.close()

    return (
        vehicle_screenshot,
        detail_screenshot,
    )


def parse_market_listings(
    html: str,
) -> list[MarketListing]:
    """从瓜子列表页HTML中解析全部候选车源。"""

    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)

    if "尝试太多了" in text or "网络错误" in text:
        raise ValueError(
            "瓜子触发访问验证，列表页暂时不可读取"
        )
    listings = []
    found_urls = set()

    pattern = re.compile(
        r"^(?P<model>.+?)\s+"
        r"(?P<year>\d{4})年\s*\|\s*"
        r"(?P<mileage>\d+(?:\.\d+)?)万公里\s*\|\s*"
        r"(?P<city>\S+).*?"
        r"(?P<price>\d+(?:\.\d+)?)\s*万"
    )

    for link in soup.find_all("a", href=True):
        relative_url = link["href"]

        if not relative_url.startswith("/car-detail/"):
            continue

        full_url = urljoin(
            "https://www.guazi.com",
            relative_url,
        )

        if full_url in found_urls:
            continue

        text = link.get_text(" ", strip=True)
        match = pattern.search(text)

        if match is None:
            continue

        mileage_km = int(
            Decimal(match.group("mileage"))
            * Decimal("10000")
        )

        price_cny = (
            Decimal(match.group("price"))
            * Decimal("10000")
        )

        listing = MarketListing(
            source_url=full_url,
            vehicle_model=match.group("model"),
            registration_year=int(
                match.group("year")
            ),
            mileage_km=mileage_km,
            city=match.group("city"),
            price_cny=price_cny,
        )

        listings.append(listing)
        found_urls.add(full_url)

    return listings



def parse_market_listing_detail(
    html: str,
    source_url: str,
) -> MarketListingDetail:
    """从瓜子详情页提取网页明确提供的案例信息。"""

    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)

    if "尝试太多了" in text or "网络错误" in text:
        raise ValueError(
            "瓜子触发访问验证，详情页暂时不可读取"
        )

    score_match = re.search(
        r"成色\s*(\d{1,3})",
        text,
    )
    grade_match = re.search(
        r"车况\s+([A-Z])\s+",
        text,
    )
    summary_match = re.search(
        r"车况\s+[A-Z]\s+(.+?)"
        r"(?=\s+理赔\s*\d+次|\s+过户\s*\d+次|\s+档案手续)",
        text,
    )
    claim_match = re.search(
        r"理赔\s*(\d+)次",
        text,
    )
    transfer_match = re.search(
        r"过户\s*(\d+)次",
        text,
    )
    use_match = re.search(
        r"使用性质\s*(非营运|营运)",
        text,
    )
    color_match = re.search(
        r"(\S+)\s+车身颜色",
        text,
    )

    return MarketListingDetail(
        source_url=source_url,
        condition_score=(
            int(score_match.group(1))
            if score_match else None
        ),
        condition_grade=(
            grade_match.group(1)
            if grade_match else None
        ),
        condition_summary=(
            summary_match.group(1)
            if summary_match else None
        ),
        claim_count=(
            int(claim_match.group(1))
            if claim_match else None
        ),
        transfer_count=(
            int(transfer_match.group(1))
            if transfer_match else None
        ),
        inspection_status=(
            "已检测" if "已检测" in text else None
        ),
        vehicle_use=(
            use_match.group(1)
            if use_match else None
        ),
        body_color=(
            color_match.group(1)
            if color_match else None
        ),
    )


def fetch_guazi_listings_from_cities(
    city_paths: list[str],
    series_path: str,
    scroll_rounds: int = 0,
) -> tuple[list[MarketListing], list[str]]:
    """抓取多个城市的瓜子车源，并按照车源链接去重。"""

    unique_listings = {}
    failed_cities = []

    normalized_series_path = (
        series_path.strip("/")
    )

    for city_path in city_paths:
        normalized_city_path = city_path.strip("/")

        url = (
            "https://www.guazi.com/"
            f"{normalized_city_path}/"
            f"{normalized_series_path}/"
        )

        try:
            html = fetch_market_page(
                url,
                scroll_rounds=scroll_rounds,
            )

            city_listings = parse_market_listings(
                html
            )

            for listing in city_listings:
                unique_listings[
                    str(listing.source_url)
                ] = listing

        except Exception:
            failed_cities.append(city_path)

    return (
        list(unique_listings.values()),
        failed_cities,
    )


def normalize_market_model(value: str) -> str:
    """删除车型名称中的空格和符号，方便比较车型。"""

    return re.sub(
        r"[^A-Z0-9\u4e00-\u9fff]",
        "",
        value.upper(),
    )


def calculate_listing_similarity(
    listing: MarketListing,
    target_year: int,
    target_mileage_km: int,
) -> float:
    """根据上牌年份和里程计算0到1之间的相似度。"""

    year_difference = abs(
        listing.registration_year - target_year
    )

    mileage_difference = abs(
        listing.mileage_km - target_mileage_km
    )

    year_score = max(
        0.0,
        1.0 - year_difference / 5,
    )

    mileage_score = max(
        0.0,
        1.0 - mileage_difference / 100_000,
    )

    return (
        year_score * 0.6
        + mileage_score * 0.4
    )


def shortlist_market_listings(
    listings: list[MarketListing],
    market_keyword: str,
    target_year: int,
    target_mileage_km: int,
    limit: int = 10,
    minimum_similarity: float = 0.70,
) -> list[MarketListing]:
    """返回车型匹配且达到最低相似度要求的候选车源。"""

    normalized_keyword = normalize_market_model(
        market_keyword
    )

    matching_listings = [
        listing
        for listing in listings
        if normalized_keyword
        in normalize_market_model(
            listing.vehicle_model
        )
    ]

    qualified_listings = [
        listing
        for listing in matching_listings
        if calculate_listing_similarity(
            listing,
            target_year,
            target_mileage_km,
        ) >= minimum_similarity
    ]

    return sorted(
        qualified_listings,
        key=lambda listing: calculate_listing_similarity(
            listing,
            target_year,
            target_mileage_km,
        ),
        reverse=True,
    )[:limit]