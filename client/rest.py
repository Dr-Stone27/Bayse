import time
import hmac
import hashlib
import base64
import asyncio
import aiohttp
import json
import logging
from typing import Optional, Dict, Any
from config import Config

logger = logging.getLogger(__name__)

class RateLimiter:
    def __init__(self, requests_per_second: int):
        self.rate = requests_per_second
        self.interval = 1.0 / requests_per_second
        self.last_called = 0.0
        self.lock = asyncio.Lock()

    async def acquire(self):
        async with self.lock:
            now = time.monotonic()
            elapsed = now - self.last_called
            if elapsed < self.interval:
                await asyncio.sleep(self.interval - elapsed)
            self.last_called = time.monotonic()

class BayseRestClient:
    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None
        self.read_limiter = RateLimiter(30)
        self.write_limiter = RateLimiter(20)

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    def _generate_signature(self, timestamp: str, method: str, path: str, body: str = "") -> str:
        body_hash = hashlib.sha256(body.encode('utf-8')).hexdigest()
        payload = f"{timestamp}.{method}.{path}.{body_hash}"
        signature_bytes = hmac.new(
            Config.SECRET_KEY.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256
        ).digest()
        return base64.b64encode(signature_bytes).decode('utf-8')

    def _get_headers(self, method: str, path: str, body: str = "") -> dict:
        timestamp = str(int(time.time()))
        headers = {
            "X-Public-Key": Config.PUBLIC_KEY,
            "Content-Type": "application/json"
        }
        # Only write endpoints need signature per spec
        if method in ["POST", "PUT", "DELETE"]:
            headers["X-Timestamp"] = timestamp
            headers["X-Signature"] = self._generate_signature(timestamp, method, path, body)
        return headers

    async def request(self, method: str, path: str, data: Optional[Dict] = None) -> Any:
        if not self.session:
            logger.warning("Session not initialized. Creating an ad-hoc session.")
            async with aiohttp.ClientSession() as session:
                self.session = session
                result = await self._execute_request(method, path, data)
            self.session = None
            return result
        return await self._execute_request(method, path, data)

    async def _execute_request(self, method: str, path: str, data: Optional[Dict] = None) -> Any:
        is_write = method in ["POST", "PUT", "DELETE"]
        limiter = self.write_limiter if is_write else self.read_limiter
        
        await limiter.acquire()
        
        url = f"{Config.REST_URL}{path}"
        body_str = json.dumps(data) if data else ""
        
        headers = self._get_headers(method, path, body_str)
        
        start_time = time.monotonic()
        try:
            async with self.session.request(method, url, headers=headers, json=data) as response:
                response.raise_for_status()
                # Empty body throws error on .json(), handle gracefully
                text = await response.text()
                result = json.loads(text) if text else {}
                rtt = (time.monotonic() - start_time) * 1000
                if isinstance(result, dict):
                    result["_rtt_ms"] = rtt
                return result
        except Exception as e:
            logger.error(f"REST API Error {method} {path}: {e}")
            raise
