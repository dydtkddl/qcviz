import os
from pathlib import Path
from unittest.mock import patch

from qcviz_mcp import env_bootstrap
from qcviz_mcp.llm.pipeline import QCVizPromptPipeline
from qcviz_mcp.llm import providers as provider_mod
from qcviz_mcp.services.gemini_agent import GeminiAgent
from qcviz_mcp.web.routes import compute as compute_route


def _write_dotenv(tmp_path: Path, text: str) -> Path:
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(text, encoding="utf-8")
    return dotenv_path


def _path_resolver(dotenv_path: Path):
    return lambda requested=None: dotenv_path if requested is None else Path(requested).resolve()


def setup_function() -> None:
    env_bootstrap._reset_env_bootstrap_state_for_tests()
    compute_route.get_qcviz_agent.cache_clear()


def teardown_function() -> None:
    env_bootstrap._reset_env_bootstrap_state_for_tests()
    compute_route.get_qcviz_agent.cache_clear()


def test_bootstrap_runtime_env_loads_gemini_key_from_dotenv(tmp_path):
    dotenv_path = _write_dotenv(tmp_path, "GEMINI_API_KEY=dotenv-key\n")

    with patch.dict(os.environ, {}, clear=True):
        loaded = env_bootstrap.bootstrap_runtime_env(dotenv_path=dotenv_path, force=True)
        assert loaded is True
        assert os.environ["GEMINI_API_KEY"] == "dotenv-key"


def test_bootstrap_runtime_env_does_not_override_existing_env(tmp_path):
    dotenv_path = _write_dotenv(tmp_path, "GEMINI_API_KEY=file-key\n")

    with patch.dict(os.environ, {"GEMINI_API_KEY": "existing-key"}, clear=True):
        loaded = env_bootstrap.bootstrap_runtime_env(dotenv_path=dotenv_path, force=True)
        assert loaded is True
        assert os.environ["GEMINI_API_KEY"] == "existing-key"


def test_bootstrap_runtime_env_manual_parser_fallback(tmp_path, monkeypatch):
    dotenv_path = _write_dotenv(tmp_path, 'GEMINI_API_KEY="manual-key"\nOPENAI_API_KEY=openai-key\n')
    monkeypatch.setattr(env_bootstrap, "_load_with_python_dotenv", lambda path, override=False: None)

    with patch.dict(os.environ, {}, clear=True):
        loaded = env_bootstrap.bootstrap_runtime_env(dotenv_path=dotenv_path, force=True)
        status = env_bootstrap.get_env_bootstrap_status()
        assert loaded is True
        assert os.environ["GEMINI_API_KEY"] == "manual-key"
        assert os.environ["OPENAI_API_KEY"] == "openai-key"
        assert status["loader"] == "manual"


def test_gemini_agent_bootstraps_project_env(tmp_path, monkeypatch):
    dotenv_path = _write_dotenv(tmp_path, "GEMINI_API_KEY=dotenv-agent-key\n")
    monkeypatch.setattr(env_bootstrap, "_resolve_dotenv_path", _path_resolver(dotenv_path))

    with patch.dict(os.environ, {}, clear=True):
        agent = GeminiAgent()
        assert agent.is_available() is True
        assert agent.api_key == "dotenv-agent-key"


def test_provider_get_provider_bootstraps_env_before_selection(tmp_path, monkeypatch):
    dotenv_path = _write_dotenv(tmp_path, "GEMINI_API_KEY=dotenv-provider-key\n")
    monkeypatch.setattr(env_bootstrap, "_resolve_dotenv_path", _path_resolver(dotenv_path))
    monkeypatch.setattr(provider_mod, "_HAS_GEMINI", True)

    class FakeGeminiProvider:
        def __init__(self, api_key=None):
            self.api_key = api_key or os.environ.get("GEMINI_API_KEY")

    monkeypatch.setattr(provider_mod, "GeminiProvider", FakeGeminiProvider)

    with patch.dict(os.environ, {}, clear=True):
        provider = provider_mod.get_provider()
        assert isinstance(provider, FakeGeminiProvider)
        assert provider.api_key == "dotenv-provider-key"


def test_compute_get_qcviz_agent_bootstraps_env_without_config_import(tmp_path, monkeypatch):
    dotenv_path = _write_dotenv(tmp_path, "GEMINI_API_KEY=dotenv-compute-key\n")
    monkeypatch.setattr(env_bootstrap, "_resolve_dotenv_path", _path_resolver(dotenv_path))

    with patch.dict(os.environ, {}, clear=True):
        compute_route.get_qcviz_agent.cache_clear()
        agent = compute_route.get_qcviz_agent()
        assert agent is not None
        assert agent.gemini_api_key == "dotenv-compute-key"
        assert agent._prompt_pipeline.gemini_api_key == "dotenv-compute-key"


def test_prompt_pipeline_sees_bootstrapped_gemini_key(tmp_path, monkeypatch):
    dotenv_path = _write_dotenv(tmp_path, "GEMINI_API_KEY=dotenv-pipeline-key\n")
    monkeypatch.setattr(env_bootstrap, "_resolve_dotenv_path", _path_resolver(dotenv_path))

    with patch.dict(os.environ, {}, clear=True):
        pipeline = QCVizPromptPipeline()
        assert pipeline._has_llm_provider() is True
        assert pipeline.gemini_api_key == "dotenv-pipeline-key"


def test_prompt_pipeline_keeps_missing_key_fallback_when_dotenv_has_no_keys(tmp_path, monkeypatch):
    dotenv_path = _write_dotenv(tmp_path, "QCVIZ_HOST=127.0.0.1\n")
    monkeypatch.setattr(env_bootstrap, "_resolve_dotenv_path", _path_resolver(dotenv_path))

    with patch.dict(os.environ, {}, clear=True):
        pipeline = QCVizPromptPipeline()
        assert pipeline._has_llm_provider() is False
        assert pipeline._detailed_no_provider_reason() == "no_gemini_key_and_no_openai_key"
        status = env_bootstrap.get_env_bootstrap_status()
        assert status["attempted"] is True
        assert status["error"] is None
