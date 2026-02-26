"""Token manager - reads kiro-cli SQLite and handles IdC token refresh."""

import json
import sqlite3
import time
from loguru import logger
from dataclasses import dataclass

import httpx

from ..config import config



@dataclass
class TokenData:
    access_token: str
    refresh_token: str
    expires_at: float  # unix timestamp
    client_id: str
    client_secret: str
    client_secret_expires_at: float
    profile_arn: str = ""


class TokenManager:
    """Manages Kiro IdC tokens with automatic refresh."""

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or config.kiro_db_path
        self._token: TokenData | None = None
        self._http = httpx.AsyncClient(timeout=15.0)

    def _read_db(self) -> TokenData:
        """Read token and registration data from kiro-cli SQLite."""
        conn = sqlite3.connect(self.db_path)
        try:
            # Read token
            row = conn.execute(
                "SELECT value FROM auth_kv WHERE key='kirocli:odic:token'"
            ).fetchone()
            if not row:
                raise RuntimeError("No kirocli token found in database")
            token_data = json.loads(row[0])

            # Read device registration (client credentials)
            row = conn.execute(
                "SELECT value FROM auth_kv WHERE key='kirocli:odic:device-registration'"
            ).fetchone()
            if not row:
                raise RuntimeError("No kirocli device registration found in database")
            reg_data = json.loads(row[0])

            # Read profile ARN from state
            profile_arn = config.profile_arn
            if not profile_arn:
                row = conn.execute(
                    "SELECT value FROM state WHERE key='api.codewhisperer.profile'"
                ).fetchone()
                if row:
                    profile = json.loads(row[0])
                    profile_arn = profile.get("arn", "")

            # Parse expires_at
            from datetime import datetime, timezone

            def parse_ts(s: str) -> float:
                s = s.rstrip("Z").split(".")[0]
                dt = datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")
                return dt.replace(tzinfo=timezone.utc).timestamp()

            return TokenData(
                access_token=token_data["access_token"],
                refresh_token=token_data["refresh_token"],
                expires_at=parse_ts(token_data["expires_at"]),
                client_id=reg_data["client_id"],
                client_secret=reg_data["client_secret"],
                client_secret_expires_at=parse_ts(
                    reg_data["client_secret_expires_at"]
                ),
                profile_arn=profile_arn,
            )
        finally:
            conn.close()

    async def _refresh_access_token(self, token: TokenData) -> str:
        """Refresh access token via IdC endpoint."""
        logger.info("Refreshing IdC access token...")
        resp = await self._http.post(
            config.idc_refresh_url,
            json={
                "clientId": token.client_id,
                "clientSecret": token.client_secret,
                "grantType": "refresh_token",
                "refreshToken": token.refresh_token,
            },
            headers={
                "Content-Type": "application/json",
                "Host": "oidc.us-east-1.amazonaws.com",
                "x-amz-user-agent": "aws-sdk-js/3.738.0 ua/2.1 os/other lang/js md/browser#unknown_unknown api/sso-oidc#3.738.0 m/E KiroIDE",
            },
        )
        if resp.status_code != 200:
            raise RuntimeError(
                f"IdC token refresh failed: {resp.status_code} {resp.text[:200]}"
            )
        data = resp.json()
        expires_in = data.get("expiresIn", 3600)
        token.access_token = data["accessToken"]
        token.expires_at = time.time() + expires_in
        logger.info(f"Token refreshed, expires in {expires_in}s")
        return token.access_token

    async def get_access_token(self) -> str:
        """Get a valid access token, refreshing if needed."""
        if self._token is None:
            self._token = self._read_db()
            logger.info(f"Loaded token from {self.db_path}")

        # Check if client_secret expired (need re-login via kiro-cli)
        if time.time() > self._token.client_secret_expires_at:
            raise RuntimeError(
                "Device registration (client_secret) expired. "
                "Please run 'kiro-cli login' to re-authenticate."
            )

        # Refresh access token if expired or about to expire (5min buffer)
        if time.time() > self._token.expires_at - 300:
            await self._refresh_access_token(self._token)

        return self._token.access_token

    @property
    def profile_arn(self) -> str:
        if self._token is None:
            self._token = self._read_db()
        return self._token.profile_arn

    async def close(self):
        await self._http.aclose()
