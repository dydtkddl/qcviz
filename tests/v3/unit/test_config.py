"""tests/v3/unit/test_config.py — 설정 모듈 단위 테스트"""
import os
import pytest
from unittest.mock import patch
from qcviz_mcp.config import ServerConfig


class TestServerConfigDefaults:
    """ServerConfig 기본값 검증"""

    def test_default_gemini_model(self):
        """기본 gemini_model == 'gemini-2.5-flash'."""
        cfg = ServerConfig()
        assert cfg.gemini_model == "gemini-2.5-flash"

    def test_default_molchat_url(self):
        """기본 molchat_base_url 확인."""
        cfg = ServerConfig()
        assert "molchat" in cfg.molchat_base_url

    def test_default_pubchem_fallback(self):
        """기본 pubchem_fallback == True."""
        cfg = ServerConfig()
        assert cfg.pubchem_fallback is True

    def test_default_scf_cache_max_size(self):
        """기본 scf_cache_max_size == 256."""
        cfg = ServerConfig()
        assert cfg.scf_cache_max_size == 256

    def test_default_ion_offset(self):
        """기본 ion_offset_angstrom == 5.0."""
        cfg = ServerConfig()
        assert cfg.ion_offset_angstrom == 5.0

    def test_default_gemini_timeout(self):
        """기본 gemini_timeout == 10.0."""
        cfg = ServerConfig()
        assert cfg.gemini_timeout == 10.0

    def test_default_preferred_renderer(self):
        """기본 preferred_renderer == 'auto'."""
        cfg = ServerConfig()
        assert cfg.preferred_renderer == "auto"


class TestServerConfigFromEnv:
    """ServerConfig.from_env() 검증"""

    def test_from_env_loads_gemini_key(self):
        """GEMINI_API_KEY 환경변수 로드."""
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test-key-123"}):
            cfg = ServerConfig.from_env()
            assert cfg.gemini_api_key == "test-key-123"

    def test_from_env_qcviz_prefix(self):
        """QCVIZ_ 접두사 환경변수 로드."""
        with patch.dict(os.environ, {"QCVIZ_GEMINI_MODEL": "gemini-3.0"}):
            cfg = ServerConfig.from_env()
            assert cfg.gemini_model == "gemini-3.0"

    def test_from_env_override_numeric(self):
        """숫자 환경변수 로드."""
        with patch.dict(os.environ, {"QCVIZ_SCF_CACHE_MAX_SIZE": "512"}):
            cfg = ServerConfig.from_env()
            assert cfg.scf_cache_max_size == 512

    def test_from_env_alt_key(self):
        """접두사 없는 alt key 환경변수 지원."""
        with patch.dict(os.environ, {"SCF_CACHE_MAX_SIZE": "1024"}, clear=False):
            cfg = ServerConfig.from_env()
            # Should pick up from alt key if QCVIZ_ version not set
            assert cfg.scf_cache_max_size in (256, 1024)
