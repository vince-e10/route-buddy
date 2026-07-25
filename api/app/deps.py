from app import registry
from app.agent.fake_llm import FakeLLM
from app.agent.llm import OpenRouterClient
from app.agent.loop import AgentServiceImpl
from app.config import settings
from app.geocode.onemap import OneMapGeocoder
from app.geocode.stub import DEMO_PLACES, StubGeocoder
from app.providers.uber import UberAdapter
from app.storage import ActionLogRepo, PendingActionRepo, SessionRepo, TripRepo


session_repo = SessionRepo()
trip_repo = TripRepo()
action_log_repo = ActionLogRepo()
pending_repo = PendingActionRepo()
provider = UberAdapter(settings)
geocoder = StubGeocoder(DEMO_PLACES) if settings.llm_mode == "fake" else OneMapGeocoder(settings)
llm = FakeLLM() if settings.llm_mode == "fake" else OpenRouterClient(settings)

agent_service = AgentServiceImpl(
    session_repo=session_repo,
    trip_repo=trip_repo,
    action_log_repo=action_log_repo,
    pending_repo=pending_repo,
    provider=provider,
    geocoder=geocoder,
    llm=llm,
)
registry.set_agent_service(agent_service)
