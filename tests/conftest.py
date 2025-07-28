import pytest

from homeassistant.setup import async_setup_component

@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Permet les intégrations custom automatiquement (pytest-homeassistant-custom-component)."""
    yield
