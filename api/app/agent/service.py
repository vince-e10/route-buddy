from typing import Literal, Protocol


class AgentService(Protocol):
    async def handle_user_message(self, session_id: str, text: str) -> None:
        """Run the agent loop and publish output without raising."""

    async def propose_action(
        self,
        session_id: str,
        action: Literal["book", "cancel"],
        target_id: str,
    ) -> None:
        """Validate a user-selected target and publish a confirmation request."""
