import os
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

CACHE_DIR = Path(os.getenv("QCVIZ_CACHE_DIR", "/tmp/qcviz_scf_cache"))

def init_cache():
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        # 다중 사용자 환경에서 다른 사용자가 접근 못하게
        try:
            os.chmod(str(CACHE_DIR), 0o700)
        except Exception:
            pass
    except Exception as e:
        logger.warning(f"Failed to create cache directory {CACHE_DIR}: {e}")

def save_to_disk(key: str, mf_obj, energy: float):
    init_cache()
    try:
        chkfile_path = CACHE_DIR / f"{key}.chk"

        from pyscf import lib
        import h5py
        with lib.H5FileWrap(str(chkfile_path), 'w') as fh5:
            fh5['scf/e_tot'] = energy
            if hasattr(mf_obj, 'mo_energy'): fh5['scf/mo_energy'] = mf_obj.mo_energy
            if hasattr(mf_obj, 'mo_occ'): fh5['scf/mo_occ'] = mf_obj.mo_occ
            if hasattr(mf_obj, 'mo_coeff'): fh5['scf/mo_coeff'] = mf_obj.mo_coeff
            if hasattr(mf_obj, 'converged'): fh5['scf/converged'] = mf_obj.converged

        # JSON instead of pickle for safety
        meta_path = CACHE_DIR / f"{key}.meta.json"
        with open(meta_path, 'w') as f:
            json.dump({"energy": energy, "chkfile": str(chkfile_path)}, f)

    except Exception as e:
        logger.warning(f"Failed to save SCF to disk cache: {e}")

def load_from_disk(key: str, mf_obj):
    # Check both old pickle format and new JSON format
    meta_path_json = CACHE_DIR / f"{key}.meta.json"
    meta_path_pkl = CACHE_DIR / f"{key}.meta"

    meta = None

    if meta_path_json.exists():
        try:
            with open(meta_path_json, 'r') as f:
                meta = json.load(f)
        except Exception as e:
            logger.warning(f"Failed to read JSON meta cache: {e}")
            return None, None
    elif meta_path_pkl.exists():
        # Legacy pickle format — read but don't trust blindly
        # Only accept if structure matches expected format
        try:
            import pickle
            with open(meta_path_pkl, 'rb') as f:
                raw = pickle.load(f)
            if isinstance(raw, dict) and "energy" in raw and "chkfile" in raw:
                meta = raw
                # Migrate to JSON
                try:
                    with open(meta_path_json, 'w') as f:
                        json.dump({"energy": raw["energy"], "chkfile": raw["chkfile"]}, f)
                    meta_path_pkl.unlink(missing_ok=True)
                except Exception:
                    pass
            else:
                return None, None
        except Exception as e:
            logger.warning(f"Failed to read legacy pickle meta cache: {e}")
            return None, None
    else:
        return None, None

    if meta is None:
        return None, None

    try:
        chkfile = meta.get("chkfile")
        if not chkfile or not os.path.exists(chkfile):
            return None, None

        import h5py
        import numpy as np
        with h5py.File(chkfile, 'r') as fh5:
            if 'scf/mo_energy' in fh5:
                val = fh5['scf/mo_energy'][()]
                mf_obj.mo_energy = val if isinstance(val, np.ndarray) else np.array(val)
            if 'scf/mo_occ' in fh5:
                val = fh5['scf/mo_occ'][()]
                mf_obj.mo_occ = val if isinstance(val, np.ndarray) else np.array(val)
            if 'scf/mo_coeff' in fh5:
                val = fh5['scf/mo_coeff'][()]
                mf_obj.mo_coeff = val if isinstance(val, np.ndarray) else np.array(val)
            if 'scf/converged' in fh5:
                mf_obj.converged = bool(fh5['scf/converged'][()])
            else:
                mf_obj.converged = True

        mf_obj.e_tot = meta.get("energy")
        return mf_obj, meta.get("energy")

    except Exception as e:
        logger.warning(f"Failed to load SCF from disk cache: {e}")

    return None, None
