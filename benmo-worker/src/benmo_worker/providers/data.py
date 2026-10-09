from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote

import httpx

from benmo_worker.errors import ConfigurationError, PermanentTaskError, RetryableTaskError
from benmo_worker.providers.http import SecureHttpDocumentProvider
from benmo_worker.schemas import (
    DocumentSnapshot,
    Observation,
    SearchHit,
    SearchResultBundle,
    SourceTier,
    SourceType,
)


def _decimal(value: Any, field: str) -> Decimal:
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError) as exc:
        raise PermanentTaskError(f"provider returned non-numeric {field}") from exc


class JsonApiClient:
    def __init__(self, timeout: float = 30.0, client: httpx.AsyncClient | None = None) -> None:
        self._owned = client is None
        self.client = client or httpx.AsyncClient(timeout=timeout, follow_redirects=False)

    async def request(self, method: str, url: str, **kwargs: Any) -> Any:
        try:
            response = await self.client.request(method, url, **kwargs)
        except httpx.TransportError as exc:
            raise RetryableTaskError(f"provider transport failure: {exc}") from exc
        if response.status_code in {408, 425, 429} or response.status_code >= 500:
            raise RetryableTaskError(f"provider returned status {response.status_code}")
        if response.status_code >= 400:
            raise PermanentTaskError(f"provider returned status {response.status_code}: {response.text[:300]}")
        try:
            data = response.json()
        except ValueError as exc:
            raise RetryableTaskError("provider returned invalid JSON") from exc
        if isinstance(data, dict):
            note = data.get("Note") or data.get("Information") or data.get("Error Message")
            if note:
                if "frequency" in str(note).casefold() or "rate limit" in str(note).casefold():
                    raise RetryableTaskError(str(note))
                raise PermanentTaskError(str(note))
        return data

    async def aclose(self) -> None:
        if self._owned:
            await self.client.aclose()


class FinnhubNewsProvider:
    def __init__(self, api_key: str, api: JsonApiClient) -> None:
        self.api_key = api_key
        self.api = api

    async def company_news(self, symbol: str, start: datetime, end: datetime) -> SearchResultBundle:
        data = await self.api.request(
            "GET",
            "https://finnhub.io/api/v1/company-news",
            params={
                "symbol": symbol,
                "from": start.date().isoformat(),
                "to": end.date().isoformat(),
                "token": self.api_key,
            },
        )
        hits = [
            SearchHit(
                url=item["url"],
                title=str(item.get("headline") or "Company news")[:500],
                snippet=str(item.get("summary") or item.get("headline") or "News item")[:20_000],
                publisher=str(item.get("source") or "Finnhub")[:500],
                published_at=datetime.fromtimestamp(item["datetime"]).astimezone() if item.get("datetime") else None,
                source_type=SourceType.NEWS,
                tier=SourceTier.C,
                query=f"{symbol} company news",
            )
            for item in data[:50]
            if isinstance(item, dict) and item.get("url")
        ]
        return SearchResultBundle(query=f"{symbol} company news", hits=hits, provider="finnhub")


class AlphaVantageProvider:
    BASE = "https://www.alphavantage.co/query"

    def __init__(self, api_key: str, api: JsonApiClient, documents: SecureHttpDocumentProvider) -> None:
        self.api_key = api_key
        self.api = api
        self.documents = documents

    async def _get(self, **params: str) -> Any:
        return await self.api.request("GET", self.BASE, params={**params, "apikey": self.api_key})

    async def company_news(self, symbol: str, start: datetime, end: datetime) -> SearchResultBundle:
        data = await self._get(
            function="NEWS_SENTIMENT",
            tickers=symbol,
            time_from=start.strftime("%Y%m%dT%H%M"),
            time_to=end.strftime("%Y%m%dT%H%M"),
            limit="50",
            sort="LATEST",
        )
        feed = data.get("feed", []) if isinstance(data, dict) else []
        hits: list[SearchHit] = []
        for item in feed:
            if not isinstance(item, dict) or not item.get("url"):
                continue
            published_at = None
            raw_time = item.get("time_published")
            if raw_time:
                try:
                    published_at = datetime.strptime(str(raw_time), "%Y%m%dT%H%M%S")
                except ValueError:
                    published_at = None
            hits.append(
                SearchHit(
                    url=item["url"],
                    title=str(item.get("title") or "Company news")[:500],
                    snippet=str(item.get("summary") or item.get("title") or "News item")[:20_000],
                    publisher=str(item.get("source") or "Alpha Vantage")[:500],
                    published_at=published_at,
                    source_type=SourceType.NEWS,
                    tier=SourceTier.C,
                    query=f"{symbol} company news",
                )
            )
        return SearchResultBundle(query=f"{symbol} company news", hits=hits, provider="alpha_vantage")

    async def financial_observation(self, metric_code: str, at: datetime) -> Observation:
        parts = metric_code.split(":", 2)
        if len(parts) != 3 or parts[0] != "financial":
            raise PermanentTaskError("financial metric must be financial:SYMBOL:field")
        _, symbol, field = parts
        for function, report_key in (
            ("INCOME_STATEMENT", "quarterlyReports"),
            ("BALANCE_SHEET", "quarterlyReports"),
            ("CASH_FLOW", "quarterlyReports"),
        ):
            data = await self._get(function=function, symbol=symbol)
            reports = data.get(report_key, []) if isinstance(data, dict) else []
            for report in reports:
                if field in report and report[field] not in {None, "None", "-"}:
                    value = _decimal(report[field], field)
                    return Observation(
                        metric_code=metric_code,
                        observed_value=value,
                        observed_at=datetime.fromisoformat(report["fiscalDateEnding"]),
                        source_adapter="alpha_vantage_financials",
                        source_ref=f"alphavantage://{function}/{symbol}/{report['fiscalDateEnding']}",
                    )
        raise PermanentTaskError(f"financial field not found: {field}")

    async def commodity_observation(self, metric_code: str, at: datetime) -> Observation:
        function = metric_code.removeprefix("commodity:").upper()
        if not function or ":" in function:
            raise PermanentTaskError("commodity metric must be commodity:FUNCTION")
        data = await self._get(function=function, interval="monthly")
        rows = data.get("data", []) if isinstance(data, dict) else []
        cutoff = at.date().isoformat()
        valid = [row for row in rows if row.get("value") not in {None, "."} and str(row.get("date", "")) <= cutoff]
        valid.sort(key=lambda row: str(row.get("date", "")), reverse=True)
        if not valid:
            raise PermanentTaskError("commodity series has no observations")
        row = valid[0]
        return Observation(
            metric_code=metric_code,
            observed_value=_decimal(row["value"], "value"),
            observed_at=datetime.fromisoformat(row["date"]),
            source_adapter="alpha_vantage_commodity",
            source_ref=f"alphavantage://commodity/{function}/{row['date']}",
        )

    async def market_observation(self, metric_code: str, at: datetime) -> Observation:
        symbol = metric_code.removeprefix("market:")
        if not symbol or ":" in symbol:
            raise PermanentTaskError("market metric must be market:SYMBOL")
        data = await self._get(function="TIME_SERIES_DAILY", symbol=symbol, outputsize="compact")
        series = data.get("Time Series (Daily)", {}) if isinstance(data, dict) else {}
        eligible = sorted((date for date in series if date <= at.date().isoformat()), reverse=True)
        if not eligible:
            raise PermanentTaskError("market series has no observation at requested date")
        date = eligible[0]
        return Observation(
            metric_code=metric_code,
            observed_value=_decimal(series[date]["4. close"], "close"),
            observed_at=datetime.fromisoformat(date),
            source_adapter="alpha_vantage_market",
            source_ref=f"alphavantage://daily/{symbol}/{date}",
        )

    async def latest_transcript(self, ticker: str) -> DocumentSnapshot:
        now = datetime.now()
        quarter = (now.month - 1) // 3 + 1
        data = await self._get(
            function="EARNINGS_CALL_TRANSCRIPT",
            symbol=ticker,
            quarter=f"{now.year}Q{quarter}",
        )
        transcript = data.get("transcript") if isinstance(data, dict) else None
        if not isinstance(transcript, list) or not transcript:
            raise PermanentTaskError("Alpha Vantage returned no transcript")
        content = "\n".join(f"{item.get('speaker', 'Unknown')}: {item.get('content', '')}" for item in transcript)
        from benmo_worker.schemas import content_sha256

        return DocumentSnapshot(
            source_url=f"https://www.alphavantage.co/query?function=EARNINGS_CALL_TRANSCRIPT&symbol={quote(ticker)}",
            source_type=SourceType.TRANSCRIPT,
            tier=SourceTier.B,
            publisher=f"{ticker} earnings call via Alpha Vantage",
            content=content,
            content_hash=content_sha256(content),
        )

    async def resolve_company(self, query: str) -> dict[str, str]:
        data = await self._get(function="SYMBOL_SEARCH", keywords=query)
        matches = data.get("bestMatches", []) if isinstance(data, dict) else []
        if not matches:
            raise PermanentTaskError(f"company not found: {query}")
        match = matches[0]
        return {
            "ticker": str(match.get("1. symbol", "")),
            "name": str(match.get("2. name", "")),
            "region": str(match.get("4. region", "")),
            "currency": str(match.get("8. currency", "")),
        }


class SECProvider:
    def __init__(
        self,
        user_agent: str,
        api: JsonApiClient,
        documents: SecureHttpDocumentProvider,
    ) -> None:
        if "@" not in user_agent:
            raise ConfigurationError("SEC user agent must contain a contact email")
        self.headers = {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}
        self.api = api
        self.documents = documents

    async def _resolve_cik(self, value: str) -> str:
        digits = value.removeprefix("CIK").strip()
        if digits.isdigit():
            return digits.zfill(10)
        tickers = await self.api.request("GET", "https://www.sec.gov/files/company_tickers.json", headers=self.headers)
        for item in tickers.values():
            if str(item.get("ticker", "")).casefold() == value.casefold():
                return str(item["cik_str"]).zfill(10)
        raise PermanentTaskError(f"SEC company not found: {value}")

    async def latest_filing(self, cik_or_ticker: str, form: str) -> DocumentSnapshot:
        cik = await self._resolve_cik(cik_or_ticker)
        submissions = await self.api.request(
            "GET", f"https://data.sec.gov/submissions/CIK{cik}.json", headers=self.headers
        )
        recent = submissions.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        try:
            index = forms.index(form)
        except ValueError as exc:
            raise PermanentTaskError(f"no recent {form} filing for {cik_or_ticker}") from exc
        accession = recent["accessionNumber"][index]
        primary = recent["primaryDocument"][index]
        accession_compact = accession.replace("-", "")
        url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_compact}/{primary}"
        snapshot = await self.documents.fetch(url)
        source_type = {
            "10-K": SourceType.SEC_10K,
            "10-Q": SourceType.SEC_10Q,
            "8-K": SourceType.SEC_8K,
        }.get(form, SourceType.WEB)
        return snapshot.model_copy(update={"source_type": source_type, "tier": SourceTier.A, "publisher": "U.S. SEC"})


class SECXbrlProvider:
    def __init__(self, user_agent: str, api: JsonApiClient) -> None:
        self.headers = {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}
        self.api = api

    async def observation(self, metric_code: str, at: datetime) -> Observation:
        parts = metric_code.split(":", 3)
        if len(parts) != 4 or parts[0] != "sec_xbrl":
            raise PermanentTaskError("SEC XBRL metric must be sec_xbrl:CIK:namespace:tag")
        _, cik_raw, namespace, tag = parts
        cik = cik_raw.removeprefix("CIK").zfill(10)
        if not cik.isdigit():
            raise PermanentTaskError("SEC XBRL CIK must be numeric")
        data = await self.api.request(
            "GET",
            f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
            headers=self.headers,
        )
        fact = data.get("facts", {}).get(namespace, {}).get(tag)
        if not fact:
            raise PermanentTaskError(f"SEC XBRL fact not found: {namespace}:{tag}")
        units = fact.get("units", {})
        values: list[dict[str, Any]] = next(iter(units.values()), [])
        eligible = [
            row
            for row in values
            if row.get("filed") and row["filed"] <= at.date().isoformat() and row.get("val") is not None
        ]
        eligible.sort(key=lambda row: (row.get("end", ""), row.get("filed", "")), reverse=True)
        if not eligible:
            raise PermanentTaskError("SEC XBRL has no fact available by the observation date")
        row = eligible[0]
        baseline = _decimal(eligible[1]["val"], "prior XBRL value") if len(eligible) > 1 else None
        return Observation(
            metric_code=metric_code,
            observed_value=_decimal(row["val"], "XBRL value"),
            baseline_value=baseline,
            observed_at=datetime.fromisoformat(row.get("end") or row["filed"]),
            source_adapter="sec_xbrl",
            source_ref=f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json#{namespace}:{tag}",
            vintage_at=datetime.fromisoformat(row["filed"]),
        )


class OfficialMacroProvider:
    def __init__(
        self,
        api: JsonApiClient,
        *,
        fred_api_key: str | None,
        bls_api_key: str | None,
        eia_api_key: str | None,
        bea_api_key: str | None = None,
    ) -> None:
        self.api = api
        self.fred_api_key = fred_api_key
        self.bls_api_key = bls_api_key
        self.eia_api_key = eia_api_key
        self.bea_api_key = bea_api_key or "samplekey"

    async def macro_observation(self, metric_code: str, at: datetime) -> Observation:
        prefix = metric_code.split(":", 1)[0].casefold()
        if prefix == "fred":
            return await self._fred(metric_code, at)
        if prefix == "bls":
            return await self._bls(metric_code, at)
        if prefix == "bea":
            return await self._bea(metric_code, at)
        if prefix == "eia":
            return await self._eia(metric_code, at)
        raise PermanentTaskError("macro metric must begin fred:, bls:, bea:, or eia:")

    async def commodity_observation(self, metric_code: str, at: datetime) -> Observation:
        if not metric_code.startswith("eia:"):
            raise PermanentTaskError("official commodity metric must begin eia:")
        return await self._eia(metric_code, at)

    async def _fred(self, metric_code: str, at: datetime) -> Observation:
        if not self.fred_api_key:
            raise ConfigurationError("FRED_API_KEY is not configured")
        series = metric_code.removeprefix("fred:")
        data = await self.api.request(
            "GET",
            "https://api.stlouisfed.org/fred/series/observations",
            params={
                "series_id": series,
                "api_key": self.fred_api_key,
                "file_type": "json",
                "observation_end": at.date().isoformat(),
                "sort_order": "desc",
                "limit": 2,
                "realtime_start": at.date().isoformat(),
                "realtime_end": at.date().isoformat(),
            },
        )
        rows = [row for row in data.get("observations", []) if row.get("value") != "."]
        if not rows:
            raise PermanentTaskError("FRED returned no vintage observation")
        row = rows[0]
        baseline = _decimal(rows[1]["value"], "previous value") if len(rows) > 1 else None
        return Observation(
            metric_code=metric_code,
            observed_value=_decimal(row["value"], "value"),
            baseline_value=baseline,
            observed_at=datetime.fromisoformat(row["date"]),
            source_adapter="fred",
            source_ref=f"https://fred.stlouisfed.org/series/{series}",
            vintage_at=at,
        )

    async def _bls(self, metric_code: str, at: datetime) -> Observation:
        series = metric_code.removeprefix("bls:")
        payload: dict[str, Any] = {
            "seriesid": [series],
            "startyear": str(at.year - 1),
            "endyear": str(at.year),
        }
        if self.bls_api_key:
            payload["registrationkey"] = self.bls_api_key
        data = await self.api.request("POST", "https://api.bls.gov/publicAPI/v2/timeseries/data/", json=payload)
        series_data = data.get("Results", {}).get("series", [])
        rows = series_data[0].get("data", []) if series_data else []
        if not rows:
            raise PermanentTaskError("BLS returned no observation")
        row = rows[0]
        baseline = _decimal(rows[1]["value"], "previous value") if len(rows) > 1 else None
        month = int(str(row["period"]).removeprefix("M")) if str(row["period"]).startswith("M") else 1
        return Observation(
            metric_code=metric_code,
            observed_value=_decimal(row["value"], "value"),
            baseline_value=baseline,
            observed_at=datetime(int(row["year"]), month, 1),
            source_adapter="bls",
            source_ref=f"https://data.bls.gov/timeseries/{series}",
        )

    async def _bea(self, metric_code: str, at: datetime) -> Observation:
        parts = metric_code.split(":")
        if len(parts) != 4:
            raise PermanentTaskError("BEA metric must be bea:dataset:table:line")
        _, dataset, table, line = parts
        data = await self.api.request(
            "GET",
            "https://apps.bea.gov/api/data/",
            params={
                "UserID": self.bea_api_key,
                "method": "GetData",
                "datasetname": dataset,
                "TableName": table,
                "LineNumber": line,
                "Year": "X",
                "ResultFormat": "JSON",
            },
        )
        rows = data.get("BEAAPI", {}).get("Results", {}).get("Data", [])
        rows = [
            row
            for row in rows
            if not str(row.get("TimePeriod", ""))[:4].isdigit() or int(str(row.get("TimePeriod"))[:4]) <= at.year
        ]
        rows.sort(key=lambda row: str(row.get("TimePeriod", "")), reverse=True)
        if not rows:
            raise PermanentTaskError("BEA returned no observation")
        row = rows[0]
        baseline = _decimal(rows[1].get("DataValue"), "prior DataValue") if len(rows) > 1 else None
        return Observation(
            metric_code=metric_code,
            observed_value=_decimal(row.get("DataValue"), "DataValue"),
            baseline_value=baseline,
            observed_at=at,
            source_adapter="bea",
            source_ref=f"https://apps.bea.gov/api/data/{dataset}/{table}/{line}",
        )

    async def _eia(self, metric_code: str, at: datetime) -> Observation:
        if not self.eia_api_key:
            raise ConfigurationError("EIA_API_KEY is not configured")
        series = metric_code.removeprefix("eia:")
        data = await self.api.request(
            "GET",
            f"https://api.eia.gov/v2/seriesid/{quote(series, safe='.-_')}",
            params={"api_key": self.eia_api_key, "length": 2, "out": "json"},
        )
        rows = data.get("response", {}).get("data", [])
        if not rows:
            raise PermanentTaskError("EIA returned no observation")
        value_field = next(
            (
                key
                for key, value in rows[0].items()
                if key not in {"period", "series-description"} and isinstance(value, (int, float))
            ),
            None,
        )
        if value_field is None:
            raise PermanentTaskError("EIA response contains no numeric value")
        return Observation(
            metric_code=metric_code,
            observed_value=_decimal(rows[0][value_field], value_field),
            baseline_value=_decimal(rows[1][value_field], value_field) if len(rows) > 1 else None,
            observed_at=at,
            source_adapter="eia",
            source_ref=f"https://www.eia.gov/opendata/browser/{quote(series)}",
            vintage_at=at,
        )
