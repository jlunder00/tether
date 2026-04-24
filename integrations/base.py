"""Abstract base classes for integration providers.

Split into OAuthProvider + SyncProvider so future integrations that use
API keys (not OAuth) or push-only delivery can implement only what they need.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from integrations.models import TaskDraft, WebhookPayload


class OAuthProvider(ABC):
    """Manages the OAuth2 token lifecycle for an integration."""

    @abstractmethod
    async def get_auth_url(self, user_id: str) -> str:
        """Return the provider's authorization URL for this user."""

    @abstractmethod
    async def handle_callback(self, user_id: str, code: str) -> None:
        """Exchange *code* for tokens and persist them."""

    @abstractmethod
    async def refresh_token(self, integration_id: str) -> None:
        """Refresh the stored access token using the refresh token."""

    @abstractmethod
    async def revoke(self, integration_id: str) -> None:
        """Revoke tokens at the provider and delete the stored integration."""


class SyncProvider(ABC):
    """Drives the data-sync lifecycle for an integration."""

    @abstractmethod
    async def register_webhook(self, integration_id: str, calendar_id: str) -> None:
        """Register a push-notification watch channel with the provider."""

    @abstractmethod
    async def renew_webhook(self, sync_state_id: str) -> None:
        """Renew an expiring watch channel."""

    @abstractmethod
    async def handle_webhook(
        self, integration_id: str, payload: WebhookPayload
    ) -> None:
        """Process an inbound push notification."""

    @abstractmethod
    async def poll(
        self,
        integration_id: str,
        calendar_id: str,
        since_cursor: str | None,
    ) -> str:
        """Fetch changes since *since_cursor* and return the new cursor."""

    @abstractmethod
    async def normalize_event(self, raw: dict) -> TaskDraft:
        """Map a provider event dict to a TaskDraft."""
