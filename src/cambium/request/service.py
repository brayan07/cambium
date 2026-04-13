"""Business logic for requests — creation, answering, and resume publishing."""

from __future__ import annotations

import logging

from cambium.models.message import Message
from cambium.queue.base import QueueAdapter
from cambium.request.model import Request, RequestStatus, RequestType
from cambium.request.store import RequestStore

logger = logging.getLogger(__name__)


class RequestService:
    """Wraps RequestStore with channel publishing for the HITL protocol."""

    def __init__(self, store: RequestStore, queue: QueueAdapter) -> None:
        self.store = store
        self.queue = queue

    def create_request(
        self,
        session_id: str | None,
        type: RequestType,
        summary: str,
        detail: str = "",
        work_item_id: str | None = None,
        options: list[str] | None = None,
        default: str | None = None,
        timeout_hours: float | None = None,
        created_by: str | None = None,
    ) -> Request:
        """Create a request and publish to input_needed channel."""
        request = Request.create(
            session_id=session_id,
            type=type,
            summary=summary,
            detail=detail,
            work_item_id=work_item_id,
            options=options,
            default=default,
            timeout_hours=timeout_hours,
            created_by=created_by,
        )
        self.store.create(request)

        self.queue.publish(Message.create(
            channel="input_needed",
            payload={
                "request_id": request.id,
                "type": request.type.value,
                "summary": request.summary,
            },
            source=created_by or "system",
        ))

        logger.info(
            "Created %s request %s: %s",
            request.type.value, request.id[:8], request.summary,
        )
        return request

    def answer_request(self, request_id: str, answer: str) -> Request:
        """Answer a request and publish to resume channel."""
        request = self.store.answer(request_id, answer)

        # Publish to resume channel — the consumer picks this up and
        # reopens the originating session with the answer injected.
        self.queue.publish(Message.create(
            channel="resume",
            payload={"user_response": request_id},
            source="system",
        ))

        logger.info("Answered request %s", request_id[:8])
        return request

    def reject_request(self, request_id: str) -> None:
        """Reject a request."""
        self.store.reject(request_id)
        logger.info("Rejected request %s", request_id[:8])

    def get_request(self, request_id: str) -> Request | None:
        return self.store.get(request_id)

    def list_pending(self) -> list[Request]:
        return self.store.list_requests(status=RequestStatus.PENDING)

    def get_summary(self) -> dict:
        """Counts by type and status for coordinator monitoring."""
        summary: dict[str, dict[str, int]] = {}
        for status in RequestStatus:
            requests = self.store.list_requests(status=status, limit=1000)
            if not requests:
                continue
            for req in requests:
                type_key = req.type.value
                if type_key not in summary:
                    summary[type_key] = {}
                summary[type_key][status.value] = summary[type_key].get(status.value, 0) + 1
        return summary
