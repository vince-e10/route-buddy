from typing import Protocol


class AgentService(Protocol):
    async def handle_user_message(self, session_id: str, text: str) -> None:
        """Run the agent loop and publish output without raising."""
