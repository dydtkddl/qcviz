from dataclasses import dataclass, field
from pathlib import Path
import os

# Auto-load .env from project root (version03/.env)
try:
    from dotenv import load_dotenv
    _env_path = Path(__file__).resolve().parents[2] / ".env"  # src/qcviz_mcp/config.py → version03/.env
    if _env_path.exists():
        load_dotenv(_env_path, override=False)
except ImportError:
    pass

@dataclass(frozen=True)
class ServerConfig:
    """서버 설정. 환경 변수 또는 기본값에서 로드. 불변."""
    
    # 서버
    host: str = "127.0.0.1"
    port: int = 8765
    transport: str = "sse"  # "sse" | "stdio"
    
    # 계산
    max_atoms: int = 50
    max_workers: int = 2
    computation_timeout_seconds: float = 300.0
    default_basis: str = "sto-3g"
    default_cube_resolution: int = 80
    
    # 캐시
    cache_max_size: int = 50
    cache_ttl_seconds: float = 3600.0
    
    # 보안
    rate_limit_capacity: int = 100
    rate_limit_refill_rate: float = 1.0
    allowed_output_root: Path = field(default_factory=lambda: Path.cwd() / "output")
    
    # 관측가능성
    log_level: str = "INFO"
    log_json: bool = False
    
    # 렌더러
    preferred_renderer: str = "auto"  # "auto" | "pyvista" | "playwright" | "py3dmol"
    
    # FIX(M1): Gemini API 설정
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    gemini_timeout: float = 10.0
    gemini_temperature: float = 0.1
    
    # FIX(M1): MolChat API 설정
    molchat_base_url: str = "http://psid.aizen.co.kr/molchat"
    molchat_timeout: float = 15.0
    
    # FIX(M1): PubChem 폴백 설정
    pubchem_timeout: float = 10.0
    pubchem_fallback: bool = True
    
    # FIX(M1): 구조 캐시 설정
    scf_cache_max_size: int = 256
    
    # FIX(M1): 이온쌍 오프셋
    ion_offset_angstrom: float = 5.0
    
    @classmethod
    def from_env(cls) -> "ServerConfig":
        """환경 변수에서 설정 로드. QCVIZ_ 접두사 + 일부 키는 접두사 없이도 지원."""
        kwargs = {}
        
        # FIX(M1): 접두사 없는 환경변수도 지원하는 키 목록
        alt_env_keys = {
            "gemini_api_key": "GEMINI_API_KEY",
            "gemini_model": "GEMINI_MODEL",
            "gemini_timeout": "GEMINI_TIMEOUT",
            "gemini_temperature": "GEMINI_TEMPERATURE",
            "molchat_base_url": "MOLCHAT_BASE_URL",
            "molchat_timeout": "MOLCHAT_TIMEOUT",
            "pubchem_timeout": "PUBCHEM_TIMEOUT",
            "scf_cache_max_size": "SCF_CACHE_MAX_SIZE",
            "ion_offset_angstrom": "ION_OFFSET_ANGSTROM",
        }
        
        for f in cls.__dataclass_fields__:
            env_key = f"QCVIZ_{f.upper()}"
            env_val = os.environ.get(env_key)
            
            # FIX(M1): 접두사 없는 키도 폴백 확인
            if env_val is None and f in alt_env_keys:
                env_val = os.environ.get(alt_env_keys[f])
            
            if env_val is not None:
                field_type = cls.__dataclass_fields__[f].type
                if field_type in ("int", int):
                    kwargs[f] = int(env_val)
                elif field_type in ("float", float):
                    kwargs[f] = float(env_val)
                elif field_type in ("bool", bool):
                    kwargs[f] = env_val.lower() in ("true", "1", "yes")
                elif "Path" in str(field_type):
                    kwargs[f] = Path(env_val)
                else:
                    kwargs[f] = env_val
        return cls(**kwargs)
