from app import registry


class BestEffortPublisher:
    async def publish(self, session_id: str, message: dict) -> None:
        try:
            await registry.get_publisher().publish(session_id, message)
        except Exception:
            pass


publisher = BestEffortPublisher()
