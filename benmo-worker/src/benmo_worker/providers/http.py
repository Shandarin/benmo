from __future__ import annotations

import asyncio
import ipaddress
import socket
from html.parser import HTMLParser
from io import BytesIO
from urllib.parse import urljoin, urlparse

import httpx
from pypdf import PdfReader

from benmo_worker.errors import PermanentTaskError, RetryableTaskError
from benmo_worker.schemas import (
    DocumentSnapshot,
    SourceTier,
    SourceType,
    content_sha256,
)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
        elif tag in {"p", "br", "div", "li", "tr", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self.parts.append(data)

    def text(self) -> str:
        lines = (" ".join(part.split()) for part in "".join(self.parts).splitlines())
        return "\n".join(line for line in lines if line)


def _is_public_address(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return not (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified
    )


async def validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise PermanentTaskError("document URL must be an unauthenticated HTTPS URL")
    if parsed.port not in {None, 443}:
        raise PermanentTaskError("non-standard document URL port is not allowed")
    try:
        addresses = await asyncio.to_thread(socket.getaddrinfo, parsed.hostname, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise RetryableTaskError(f"cannot resolve document host: {parsed.hostname}") from exc
    if not addresses or any(not _is_public_address(str(item[4][0])) for item in addresses):
        raise PermanentTaskError("document URL resolves to a non-public address")


def classify_source(url: str) -> tuple[SourceType, SourceTier, str]:
    host = (urlparse(url).hostname or "").lower()
    if host.endswith("sec.gov"):
        return SourceType.SEC_10K, SourceTier.A, "U.S. SEC"
    if any(host.endswith(domain) for domain in ("eia.gov", "bls.gov", "bea.gov", "stlouisfed.org")):
        return SourceType.OFFICIAL_DATA, SourceTier.A, host
    if host.startswith("investor.") or ".investor." in host:
        return SourceType.COMPANY_IR, SourceTier.A, host
    return SourceType.WEB, SourceTier.D, host or "web"


class SecureHttpDocumentProvider:
    def __init__(
        self,
        *,
        timeout: float = 30.0,
        max_bytes: int = 10_000_000,
        user_agent: str = "Benmo Research contact@example.invalid",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.max_bytes = max_bytes
        self._owned_client = client is None
        self.client = client or httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
        )

    async def fetch(self, url: str) -> DocumentSnapshot:
        current = url
        response: httpx.Response | None = None
        for _ in range(5):
            await validate_public_url(current)
            try:
                async with self.client.stream("GET", current) as streamed:
                    if streamed.status_code in {301, 302, 303, 307, 308}:
                        location = streamed.headers.get("location")
                        if not location:
                            raise PermanentTaskError("redirect has no location")
                        current = urljoin(current, location)
                        continue
                    if streamed.status_code in {408, 425, 429} or streamed.status_code >= 500:
                        raise RetryableTaskError(f"source returned retryable status {streamed.status_code}")
                    if streamed.status_code >= 400:
                        raise PermanentTaskError(f"source returned status {streamed.status_code}")
                    content_length = streamed.headers.get("content-length")
                    if content_length and int(content_length) > self.max_bytes:
                        raise PermanentTaskError("source document exceeds configured size limit")
                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in streamed.aiter_bytes():
                        total += len(chunk)
                        if total > self.max_bytes:
                            raise PermanentTaskError("source document exceeds configured size limit")
                        chunks.append(chunk)
                    body = b"".join(chunks)
                    response = httpx.Response(
                        streamed.status_code,
                        headers=streamed.headers,
                        content=body,
                        request=streamed.request,
                    )
                    break
            except httpx.TransportError as exc:
                raise RetryableTaskError(f"document fetch failed: {exc}") from exc
        if response is None:
            raise PermanentTaskError("too many document redirects")
        content_type = response.headers.get("content-type", "application/octet-stream")
        text = self._extract(response.content, content_type)
        if not text.strip():
            raise PermanentTaskError("document has no extractable text")
        source_type, tier, publisher = classify_source(current)
        return DocumentSnapshot(
            source_url=current,
            source_type=source_type,
            tier=tier,
            publisher=publisher,
            content_type=content_type,
            content=text,
            content_hash=content_sha256(text),
        )

    def _extract(self, body: bytes, content_type: str) -> str:
        lowered = content_type.casefold()
        if "pdf" in lowered or body.startswith(b"%PDF"):
            try:
                reader = PdfReader(BytesIO(body))
                return "\n\n".join(page.extract_text() or "" for page in reader.pages)
            except Exception as exc:
                raise PermanentTaskError(f"cannot parse PDF: {exc}") from exc
        encoding = "utf-8"
        if "charset=" in lowered:
            encoding = content_type.split("charset=", 1)[1].split(";", 1)[0].strip()
        text = body.decode(encoding, errors="replace")
        if "html" in lowered or "<html" in text[:1_000].casefold():
            parser = _TextExtractor()
            parser.feed(text)
            return parser.text()
        return text.replace("\x00", "")

    async def aclose(self) -> None:
        if self._owned_client:
            await self.client.aclose()
