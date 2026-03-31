"""시각화 백엔드 — Enterprise v3.5 UI/UX Restoration & Upgrade.

v3.5 패치 내역:
1. [RESTORE] v2.3.0의 모든 UI 요소 100% 복구 + v4 기능 통합.
2. [UPGRADE] Enterprise-grade sidebar layout, floating toolbar.
3. [ADD] Isovalue/Opacity sliders, Representation toggle, Labels,
   Charges overlay, Screenshot, Keyboard shortcuts.
4. [STYLE] Clean commercial SaaS aesthetic — white background,
   refined typography, subtle shadows.
5. [FIX] Flexbox scroll (min-height:0), Orbital clipping (zoom & slab), 
   White background, Resize handling.
"""

from __future__ import annotations

import base64
import html
import json
import logging
import re
import textwrap
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from qcviz_mcp.backends.base import VisualizationBackend
from qcviz_mcp.backends.registry import registry

logger = logging.getLogger("qcviz_mcp.viz_backend")


_ESP_PRESET_ORDER = (
    "rwb",
    "viridis",
    "inferno",
    "spectral",
    "nature",
    "acs",
    "rsc",
    "matdark",
    "grey",
    "hicon",
)

def _json_for_script(obj) -> str:
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")

def _build_esp_select_options(presets: dict) -> str:
    seen = set()
    items = []

    for key in _ESP_PRESET_ORDER:
        if key in presets:
            items.append((key, presets[key]))
            seen.add(key)

    for key, value in presets.items():
        if key not in seen:
            items.append((key, value))

    lines = []
    for key, spec in items:
        label = html.escape(str(spec.get("name") or key))
        value = html.escape(str(key))
        selected = ' selected' if key == "rwb" else ""
        lines.append(f'<option value="{value}"{selected}>{label}</option>')

    return "\n".join(lines)


ESP_PRESETS_DATA = {
    "rwb": {
        "name": "Standard RWB",
        "gradient_type": "rwb",
        "colors": [],
    },
    "nature": {
        "name": "Nature",
        "gradient_type": "linear",
        "colors": ["#e91e63", "#ffffff", "#00bcd4"],
    },
    "acs": {
        "name": "ACS Gold",
        "gradient_type": "linear",
        "colors": ["#e65100", "#fffde7", "#4a148c"],
    },
    "rsc": {
        "name": "RSC Pastel",
        "gradient_type": "linear",
        "colors": ["#ff8a80", "#f5f5f5", "#82b1ff"],
    },
    "viridis": {
        "name": "Viridis",
        "gradient_type": "linear",
        "colors": [
            "#440154", "#31688e", "#21918c",
            "#35b779", "#fde725",
        ],
    },
    "inferno": {
        "name": "Inferno",
        "gradient_type": "linear",
        "colors": [
            "#000004", "#420a68", "#932667",
            "#dd513a", "#fcffa4",
        ],
    },
    "spectral": {
        "name": "Spectral",
        "gradient_type": "linear",
        "colors": [
            "#d53e4f", "#fc8d59", "#fee08b",
            "#e6f598", "#99d594", "#3288bd",
        ],
    },
    "grey": {
        "name": "Greyscale",
        "gradient_type": "linear",
        "colors": ["#212121", "#9e9e9e", "#fafafa"],
    },
    "matdark": {
        "name": "Materials Dark",
        "gradient_type": "linear",
        "colors": ["#ff6f00", "#1a1a2e", "#00e5ff"],
    },
    "hicon": {
        "name": "High Contrast",
        "gradient_type": "linear",
        "colors": ["#ff1744", "#000000", "#2979ff"],
    },
}


ESP_PRESETS_DATA = {
    "rwb": {
        "name": "Standard RWB",
        "gradient_type": "rwb",
        "colors": [],
    },
    "nature": {
        "name": "Nature",
        "gradient_type": "linear",
        "colors": ["#e91e63", "#ffffff", "#00bcd4"],
    },
    "acs": {
        "name": "ACS Gold",
        "gradient_type": "linear",
        "colors": ["#e65100", "#fffde7", "#4a148c"],
    },
    "rsc": {
        "name": "RSC Pastel",
        "gradient_type": "linear",
        "colors": ["#ff8a80", "#f5f5f5", "#82b1ff"],
    },
    "viridis": {
        "name": "Viridis",
        "gradient_type": "linear",
        "colors": [
            "#440154", "#31688e", "#21918c",
            "#35b779", "#fde725",
        ],
    },
    "inferno": {
        "name": "Inferno",
        "gradient_type": "linear",
        "colors": [
            "#000004", "#420a68", "#932667",
            "#dd513a", "#fcffa4",
        ],
    },
    "spectral": {
        "name": "Spectral",
        "gradient_type": "linear",
        "colors": [
            "#d53e4f", "#fc8d59", "#fee08b",
            "#e6f598", "#99d594", "#3288bd",
        ],
    },
    "grey": {
        "name": "Greyscale",
        "gradient_type": "linear",
        "colors": ["#212121", "#9e9e9e", "#fafafa"],
    },
    "matdark": {
        "name": "Materials Dark",
        "gradient_type": "linear",
        "colors": ["#ff6f00", "#1a1a2e", "#00e5ff"],
    },
    "hicon": {
        "name": "High Contrast",
        "gradient_type": "linear",
        "colors": ["#ff1744", "#000000", "#2979ff"],
    },
}


def build_web_visualization_payload(payload: DashboardPayload) -> dict:
    orbitals = []
    selected_key = None

    for i, orb in enumerate(payload.orbitals or []):
        key = f"orb:{orb.index}"
        item = {
            "key": key,
            "mo_index": int(orb.index),
            "label": orb.label or f"MO {orb.index}",
            "energy_ev": float(orb.energy_ev or 0.0),
            "occupation": None,
            "spin": "restricted",
            "cube_b64": orb.cube_b64,
        }
        orbitals.append(item)

        label_upper = str(item["label"]).upper()
        if selected_key is None and label_upper == "HOMO":
            selected_key = key

    if selected_key is None and orbitals:
        selected_key = orbitals[0]["key"]

    esp_available = bool(
        payload.esp_data
        and payload.esp_data.density_cube_b64
        and payload.esp_data.potential_cube_b64
    )

    esp_range = [-0.05, 0.05]
    if payload.esp_data:
        esp_range = [
            float(payload.esp_data.vmin),
            float(payload.esp_data.vmax),
        ]

    return {
        "status": "ready" if orbitals or esp_available else "empty",
        "defaults": {
            "orbital_iso": 0.02,
            "orbital_opacity": 0.82,
            "esp_iso": 0.002,
            "esp_opacity": 0.80,
            "esp_range": esp_range,
            "esp_preset": "rwb",
        },
        "orbitals": {
            "available": bool(orbitals),
            "items": orbitals,
            "selected_key": selected_key,
        },
        "esp": {
            "available": esp_available,
            "density_cube_b64": payload.esp_data.density_cube_b64 if payload.esp_data else None,
            "potential_cube_b64": payload.esp_data.potential_cube_b64 if payload.esp_data else None,
            "presets": ESP_PRESETS_DATA,
        },
        "warnings": [],
        "meta": {
            "molecule_name": payload.molecule_name,
            "method": payload.method,
            "basis": payload.basis,
            "energy_hartree": payload.energy_hartree,
        },
    }


class CubeNormalizer:
    _FLOAT_RE = re.compile(
        r"[+-]?(?:\d+\.?\d*|\.\d+)[EeDd][+-]?\d+|[+-]?(?:\d+\.?\d*|\.\d+)"
    )

    @classmethod
    def normalize(cls, cube_text: str) -> str:
        if not cube_text or not cube_text.strip():
            return ""
        raw = cube_text.replace("\r\n", "\n").replace("\r", "\n")
        lines = raw.split("\n")
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        if len(lines) < 7:
            return cube_text
        try:
            out = [lines[0], lines[1]]
            toks2 = lines[2].split()
            na = abs(int(toks2[0]))
            has_dset = int(toks2[0]) < 0
            line2 = "%5d %11s %11s %11s" % (na, toks2[1], toks2[2], toks2[3])
            if len(toks2) > 4:
                line2 += " %4s" % toks2[4]
            out.append(line2)
            for i in range(3):
                toks = lines[3 + i].split()
                out.append(
                    "%5d %11s %11s %11s"
                    % (abs(int(toks[0])), toks[1], toks[2], toks[3])
                )
            for ia in range(na):
                toks = lines[6 + ia].split()
                if len(toks) >= 5:
                    out.append(
                        "%5s %11s %11s %11s %11s"
                        % (toks[0], toks[1], toks[2], toks[3], toks[4])
                    )
                else:
                    out.append(lines[6 + ia])
            ds = 6 + na + (1 if has_dset else 0)
            db = " ".join(lines[ds:]).replace("D", "E").replace("d", "e")
            floats = cls._FLOAT_RE.findall(db)
            if not floats:
                return cube_text
            for i in range(0, len(floats), 6):
                chunk = floats[i : i + 6]
                out.append("  ".join("%13.5E" % float(v) for v in chunk))
            return "\n".join(out) + "\n"
        except Exception:
            return cube_text

    @classmethod
    def to_base64(cls, cube_text: str) -> str:
        return base64.b64encode(
            cls.normalize(cube_text).encode("utf-8")
        ).decode("ascii")


@dataclass
class OrbitalRenderData:
    index: int
    label: str
    cube_b64: str
    energy_ev: float = 0.0


@dataclass
class ESPRenderData:
    density_cube_b64: str
    potential_cube_b64: str
    vmin: float = -0.1
    vmax: float = 0.1


@dataclass
class DashboardPayload:
    molecule_name: str
    xyz_data: str
    atom_symbols: List[str]
    basis: str
    method: str
    energy_hartree: float
    orbitals: List[OrbitalRenderData] = field(default_factory=list)
    charges: Dict[str, float] = field(default_factory=dict)
    esp_data: Optional[ESPRenderData] = None


class DashboardTemplateEngine:
    @classmethod
    def render(cls, p: DashboardPayload) -> str:
        xyz_b64 = base64.b64encode(
            p.xyz_data.strip().encode("utf-8")
        ).decode("ascii")
        formula = cls._formula(p.atom_symbols)

        orb_data_list = [
            {
                "ix": o.index,
                "label": o.label,
                "b64": o.cube_b64,
                "ev": o.energy_ev,
            }
            for o in p.orbitals
        ]

        charge_vals = list(p.charges.values()) if p.charges else []
        atom_labels = [
            "%s%d" % (s, i + 1) for i, s in enumerate(p.atom_symbols)
        ]

        esp_presets_data = ESP_PRESETS_DATA

        charge_html = ""
        if p.charges:
            mx = max(abs(v) for v in p.charges.values()) or 1.0
            for i, (sym, val) in enumerate(p.charges.items()):
                wp = abs(val) / mx * 50
                color_class = "charge-pos" if val > 0 else "charge-neg"
                margin = "50%" if val >= 0 else f"{50 - wp:.1f}%"
                charge_html += (
                    f'<div class="charge-row" data-idx="{i}" onclick="QV.lockAtom({i})">'
                    f'<div class="charge-label">{sym}</div>'
                    f'<div class="charge-bar-container">'
                    f'<div class="charge-bar-track">'
                    f'<div class="charge-bar-fill {color_class}" style="width:{wp:.1f}%; left:{margin}"></div>'
                    f'<div class="charge-zero-line"></div>'
                    f'</div>'
                    f'</div>'
                    f'<div class="charge-val {color_class}">{val:+.4f}</div>'
                    f'</div>'
                )

        orb_list_html = "".join(
            [
                f'<li data-idx="{i}" onclick="QV.showOrb({i})">'
                f'<div class="orb-idx">{i+1}</div>'
                f'<div class="orb-name">{o.label}</div>'
                f'<div class="orb-energy">{o.energy_ev:.3f} eV</div>'
                f'</li>'
                for i, o in enumerate(p.orbitals)
            ]
        )

        eden, epot, emin, emax = ("", "", -0.1, 0.1)
        if p.esp_data:
            eden = p.esp_data.density_cube_b64
            epot = p.esp_data.potential_cube_b64
            emin = p.esp_data.vmin
            emax = p.esp_data.vmax

        wiki_map = {
            "H2O": "Water",
            "CO2": "Carbon_dioxide",
            "C10H8": "Naphthalene",
            "C6H6": "Benzene",
            "NH3": "Ammonia",
            "CH4": "Methane",
        }
        wiki_q = wiki_map.get(formula, p.molecule_name)

        html = _DASHBOARD_HTML
        html = html.replace("%%MOL_NAME%%", html.escape(p.molecule_name))
        html = html.replace("%%CSS%%", _DASHBOARD_CSS)

        # Prepare JS with presets
        dashboard_js = _DASHBOARD_JS.replace("%%ESP_PRESETS_JSON%%", _json_for_script(esp_presets_data))
        html = html.replace("%%JS%%", dashboard_js)

        html = html.replace("%%ESP_OPTIONS%%", _build_esp_select_options(esp_presets_data))
        html = html.replace("%%XYZ_B64%%", xyz_b64)
        html = html.replace("%%ORB_JSON%%", json.dumps(orb_data_list))
        html = html.replace(
            "%%CHARGES_VAL_JSON%%", json.dumps(charge_vals)
        )
        html = html.replace(
            "%%ATOM_LABELS_JSON%%", json.dumps(atom_labels)
        )
        html = html.replace("%%WIKI_QUERY%%", json.dumps(wiki_q))
        html = html.replace(
            "%%ESP_PRESETS_DATA%%", json.dumps(esp_presets_data)
        )
        html = html.replace("%%EDEN_B64%%", eden)
        html = html.replace("%%EPOT_B64%%", epot)
        html = html.replace("%%EMIN%%", str(emin))
        html = html.replace("%%EMAX%%", str(emax))
        html = html.replace("%%BASIS%%", p.basis)
        html = html.replace("%%METHOD%%", p.method)
        html = html.replace(
            "%%ENERGY%%", "%.6f" % p.energy_hartree
        )
        html = html.replace("%%FORMULA%%", formula)
        html = html.replace("%%ORB_LIST%%", orb_list_html)
        html = html.replace("%%CHARGE_BARS%%", charge_html)
        return html

    @staticmethod
    def _formula(symbols):
        c = Counter(symbols)
        res = []
        for e in ["C", "H"]:
            if e in c:
                n = c.pop(e)
                res.append(e + (str(n) if n > 1 else ""))
        for e in sorted(c.keys()):
            n = c[e]
            res.append(e + (str(n) if n > 1 else ""))
        return "".join(res)


def build_web_visualization_payload(payload: DashboardPayload) -> dict:
    orbitals = []
    selected_key = None

    for i, orb in enumerate(payload.orbitals or []):
        key = f"orb:{orb.index}"
        item = {
            "key": key,
            "mo_index": int(orb.index),
            "label": orb.label or f"MO {orb.index}",
            "energy_ev": float(orb.energy_ev or 0.0),
            "occupation": None,
            "spin": "restricted",
            "cube_b64": orb.cube_b64,
        }
        orbitals.append(item)

        label_upper = str(item["label"]).upper()
        if selected_key is None and label_upper == "HOMO":
            selected_key = key

    if selected_key is None and orbitals:
        selected_key = orbitals[0]["key"]

    esp_available = bool(
        payload.esp_data
        and payload.esp_data.density_cube_b64
        and payload.esp_data.potential_cube_b64
    )

    esp_range = [-0.05, 0.05]
    if payload.esp_data:
        esp_range = [
            float(payload.esp_data.vmin),
            float(payload.esp_data.vmax),
        ]

    return {
        "status": "ready" if orbitals or esp_available else "empty",
        "defaults": {
            "orbital_iso": 0.02,
            "orbital_opacity": 0.82,
            "esp_iso": 0.002,
            "esp_opacity": 0.80,
            "esp_range": esp_range,
            "esp_preset": "rwb",
        },
        "orbitals": {
            "available": bool(orbitals),
            "items": orbitals,
            "selected_key": selected_key,
        },
        "esp": {
            "available": esp_available,
            "density_cube_b64": payload.esp_data.density_cube_b64 if payload.esp_data else None,
            "potential_cube_b64": payload.esp_data.potential_cube_b64 if payload.esp_data else None,
            "presets": ESP_PRESETS_DATA,
        },
        "warnings": [],
        "meta": {
            "molecule_name": payload.molecule_name,
            "method": payload.method,
            "basis": payload.basis,
            "energy_hartree": payload.energy_hartree,
        },
    }


class Py3DmolBackend(VisualizationBackend):
    @classmethod
    def name(cls):
        return "py3dmol"

    @staticmethod
    def is_available():
        return True

    def prepare_web_visualization_payload(self, payload):
        return build_web_visualization_payload(payload)

    def render_dashboard(self, payload):
        return DashboardTemplateEngine.render(payload)

    def prepare_orbital_data(self, c, i, l, energy=0.0):
        return OrbitalRenderData(
            i, l, CubeNormalizer.to_base64(c), energy
        )

    def prepare_esp_data(self, d, p, vmin, vmax):
        return ESPRenderData(
            CubeNormalizer.to_base64(d),
            CubeNormalizer.to_base64(p),
            vmin,
            vmax,
        )

    def render_molecule(self, xyz, style="stick"):
        return _SIMPLE_MOL.replace(
            "%%XYZ_B64%%",
            base64.b64encode(xyz.encode()).decode(),
        )

    def render_orbital(self, xyz, cube, isovalue=0.02):
        return _SIMPLE_ORB.replace(
            "%%XYZ_B64%%",
            base64.b64encode(xyz.encode()).decode(),
        ).replace("%%CUBE_B64%%", CubeNormalizer.to_base64(cube))

    def render_orbital_from_cube(
        self, cube_text, geometry_xyz, isovalue=0.02
    ):
        return self.render_orbital(geometry_xyz, cube_text, isovalue)


registry.register(Py3DmolBackend)

_DASHBOARD_CSS = """\
<style>
/* ─────────────────────────────────────────────
   QCViz Enterprise Web — style.css
   Scientific SaaS + Minimal Enterprise Dashboard
   CSS-only redesign for existing HTML/JS
   ───────────────────────────────────────────── */

/* ── Design Tokens ─────────────────────────── */
:root {
  /* ── 배경 계층 (Surface Hierarchy) ── */
  --bg-app: #f1f5fb;
  --bg-app-gradient: radial-gradient(ellipse at top left, rgba(79, 70, 229, 0.07), transparent 40%),
                     radial-gradient(ellipse at bottom right, rgba(2, 132, 199, 0.05), transparent 35%),
                     linear-gradient(180deg, #f8fbff 0%, #f1f5fb 100%);
  --surface-0: rgba(255, 255, 255, 0.85);
  --surface-1: #ffffff;
  --surface-2: #f8fbff;
  --surface-3: linear-gradient(180deg, #f0f4ff 0%, #e8eeff 100%);

  /* ── 텍스트 ── */
  --text-primary: #0f172a;
  --text-secondary: #475569;
  --text-muted: #94a3b8;
  --text-on-brand: #ffffff;

  /* ── 브랜드 (Indigo 계열) ── */
  --brand: #4f46e5;
  --brand-hover: #4338ca;
  --brand-strong: #3730a3;
  --brand-muted: #e0e7ff;
  --brand-subtle: #eef2ff;

  /* ── 보조 액센트 (Cyan/Sky) ── */
  --accent: #0284c7;
  --accent-hover: #0369a1;
  --accent-muted: #e0f2fe;
  --accent-subtle: #f0f9ff;

  /* ── 상태색 (Status) ── */
  --success: #16a34a;
  --success-bg: #f0fdf4;
  --success-border: #bbf7d0;
  --warning: #d97706;
  --warning-bg: #fffbeb;
  --warning-border: #fde68a;
  --danger: #dc2626;
  --danger-bg: #fef2f2;
  --danger-border: #fecaca;
  --info: #0284c7;
  --info-bg: #f0f9ff;
  --info-border: #bae6fd;

  /* ── 보더 & 구분선 ── */
  --border: #dbe4f0;
  --border-strong: #c7d2fe;
  --border-subtle: #e8edf5;
  --divider: rgba(148, 163, 184, 0.18);

  /* ── 그림자 ── */
  --shadow-xs: 0 1px 2px rgba(15, 23, 42, 0.04);
  --shadow-sm: 0 2px 8px rgba(15, 23, 42, 0.05);
  --shadow-md: 0 8px 24px rgba(15, 23, 42, 0.06);
  --shadow-lg: 0 18px 40px rgba(15, 23, 42, 0.08), 0 6px 16px rgba(15, 23, 42, 0.04);
  --shadow-brand: 0 4px 14px rgba(79, 70, 229, 0.25);

  /* ── 라운딩 ── */
  --radius-sm: 8px;
  --radius-md: 12px;
  --radius-lg: 16px;
  --radius-xl: 20px;
  --radius-full: 9999px;

  /* ── 트랜지션 ── */
  --ease-out: cubic-bezier(.2, .8, .2, 1);
  --duration-fast: 150ms;
  --duration-normal: 220ms;
  --duration-slow: 320ms;

  /* ── 타이포그래피 ── */
  --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  --font-mono: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace;
  --font-size-xs: 11px;
  --font-size-sm: 13px;
  --font-size-base: 14px;
  --font-size-md: 15px;
  --font-size-lg: 18px;
  --font-size-xl: 22px;
  --font-size-2xl: 28px;

  /* ── Supplemental tokens ── */
  --transparent: transparent;
  --focus-ring: rgba(79, 70, 229, 0.15);
  --focus-ring-strong: rgba(79, 70, 229, 0.12);
  --surface-overlay: rgba(255, 255, 255, 0.72);
  --surface-overlay-strong: rgba(248, 251, 255, 0.84);
  --pulse-shadow-success: rgba(22, 163, 74, 0.22);
  --pulse-shadow-brand: rgba(79, 70, 229, 0.18);
  --scrollbar-thumb: #dbe4f0;
  --scrollbar-thumb-hover: #cbd5e1;
  --scrollbar-track: transparent;
  --code-bg: #0f172a;
  --code-border: #334155;
  --code-text: #e2e8f0;
  --code-muted: #94a3b8;
  --code-button-bg: rgba(255, 255, 255, 0.08);
  --code-button-border: rgba(255, 255, 255, 0.14);
  --code-button-hover: rgba(255, 255, 255, 0.16);
  --selection-bg: #e0e7ff;
  --selection-text: #312e81;
}

/* ── Reset / Base ─────────────────────────── */
*,
*::before,
*::after {
  box-sizing: border-box;
}

html {
  font-size: 16px;
  scroll-behavior: smooth;
  height: 100%;
  overflow: hidden;
}

html,
body {
  margin: 0;
  padding: 0;
  min-height: 100%;
  font-family: var(--font-sans);
  background: var(--bg-app-gradient);
  color: var(--text-primary);
  line-height: 1.6;
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}

body {
  height: 100%;
  min-height: 0; /* CRITICAL for nested flex scroll */
  display: flex;
  flex-direction: column;
}

/* ── QCViz-MCP Specific Layout Mappings ── */

.layout-container {
  display: flex;
  height: 100vh;
  width: 100vw;
  background: var(--bg-app-gradient);
  overflow: hidden;
}

.main-area {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  padding: 16px;
  gap: 16px;
}

.top-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 24px;
  background: var(--surface-0);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  backdrop-filter: blur(12px);
  flex: 0 0 auto;
}

.logo-area {
  display: flex;
  align-items: center;
  gap: 12px;
  font-weight: 700;
  font-size: var(--font-size-lg);
  color: var(--text-primary);
}

.logo-icon {
  width: 32px;
  height: 32px;
  background: linear-gradient(135deg, var(--brand), var(--accent));
  color: white;
  border-radius: var(--radius-md);
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 800;
}

.content-row {
  display: flex;
  flex: 1 1 auto;
  gap: 16px;
  min-height: 0; /* allows flex scrolling child */
}

.sidebar {
  display: flex;
  flex-direction: column;
  width: 360px;
  flex: 0 0 360px;
  background: var(--surface-0);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  backdrop-filter: blur(12px);
  overflow: hidden;
}

.sidebar-header {
  padding: 16px 20px;
  border-bottom: 1px solid var(--divider);
  background: var(--surface-1);
}

.sidebar-header h3 {
  font-size: var(--font-size-md);
  font-weight: 700;
  margin: 0;
}

.sidebar-scroll {
  flex: 1 1 auto;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.viewer-container {
  flex: 1 1 auto;
  position: relative;
  background: var(--surface-1);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}

.info-grid {
  display: grid;
  grid-template-columns: minmax(80px, max-content) 1fr;
  gap: 8px 12px;
  font-size: var(--font-size-sm);
}

.info-label {
  color: var(--text-muted);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  font-size: var(--font-size-xs);
}

.info-value {
  color: var(--text-primary);
  font-family: var(--font-mono);
  font-weight: 500;
}

.wiki-box {
  margin-top: 12px;
  padding: 12px;
  background: var(--surface-2);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  font-size: var(--font-size-sm);
  color: var(--text-secondary);
  line-height: 1.5;
}

.slider-group {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 12px;
}

.slider-group label {
  display: flex;
  justify-content: space-between;
  font-size: var(--font-size-xs);
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.slider-group .val {
  color: var(--brand);
  font-family: var(--font-mono);
}

input[type=range] {
  -webkit-appearance: none;
  width: 100%;
  background: transparent;
  padding: 0;
  border: none;
  box-shadow: none;
}

input[type=range]::-webkit-slider-thumb {
  -webkit-appearance: none;
  height: 16px;
  width: 16px;
  border-radius: 50%;
  background: var(--brand);
  cursor: pointer;
  margin-top: -6px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.3);
}

input[type=range]::-webkit-slider-runnable-track {
  width: 100%;
  height: 4px;
  cursor: pointer;
  background: var(--border-strong);
  border-radius: 2px;
}

/* ESP Colorbar */
.esp-colorbar {
  height: 8px;
  border-radius: 4px;
  margin-top: 4px;
}

.esp-labels {
  display: flex;
  justify-content: space-between;
  font-size: 10px;
  font-family: var(--font-mono);
  color: var(--text-muted);
  margin-top: 4px;
}

/* Lists */
.orb-list, .charge-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.orb-item, .charge-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background: var(--surface-1);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
}

.orb-item:hover, .charge-row:hover {
  border-color: var(--border-strong);
  background: var(--brand-subtle);
}

.orb-item.active, .charge-row.active {
  background: var(--brand-muted);
  border-color: var(--brand);
}

.orb-idx, .c-atom {
  font-family: var(--font-mono);
  font-weight: 600;
  font-size: var(--font-size-sm);
  color: var(--text-primary);
  width: 30px;
}

.orb-label {
  flex: 1;
  font-size: var(--font-size-xs);
  color: var(--text-secondary);
}

.orb-ev, .c-val {
  font-family: var(--font-mono);
  font-size: var(--font-size-sm);
  color: var(--brand-strong);
  font-weight: 600;
}

.charge-row .c-val.pos { color: var(--danger); }
.charge-row .c-val.neg { color: var(--brand); }

#v3d {
  width: 100%;
  height: 100%;
}

.panel {
  background: var(--surface-0);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-md);
  padding: 16px;
  display: flex;
  flex-direction: column;
}

.panel-title {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--divider);
  font-size: var(--font-size-sm);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--text-secondary);
}

.badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  border-radius: var(--radius-full);
  font-size: var(--font-size-xs);
  font-weight: 700;
  letter-spacing: 0.02em;
  border: 1px solid var(--border);
  background: var(--surface-2);
  color: var(--text-secondary);
}

.toolbar {
  display: flex;
  gap: 8px;
}

button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 8px 14px;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border);
  background: var(--surface-1);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all var(--duration-fast) var(--ease-out);
}

button:hover {
  border-color: var(--border-strong);
  color: var(--text-primary);
}

button.active {
  background: var(--brand-muted);
  border-color: var(--brand);
  color: var(--brand-strong);
  font-weight: 600;
}

/* ── Status display (bottom right) ── */
#status-display {
  position: absolute;
  bottom: 16px;
  right: 16px;
  background: rgba(15, 23, 42, 0.7);
  color: #fff;
  padding: 6px 12px;
  border-radius: 6px;
  font-size: 12px;
  font-family: var(--font-mono);
  backdrop-filter: blur(4px);
  pointer-events: none;
  z-index: 10;
}

/* ── Loader ── */
#loader {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  z-index: 50;
  background: rgba(255, 255, 255, 0.9);
  padding: 16px 24px;
  border-radius: 8px;
  box-shadow: var(--shadow-md);
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 12px;
}
.spinner {
  width: 20px;
  height: 20px;
  border: 3px solid var(--border);
  border-top-color: var(--brand);
  border-radius: 50%;
  animation: spin 1s linear infinite;
}
@keyframes spin { 100% { transform: rotate(360deg); } }
</style>
"""

_DASHBOARD_JS = """\
<script>
/* ============================================================
   QCViz-MCP Enterprise v3.5 — Dashboard JS (Bug-Fixed)
   ============================================================ */

var QV = window.QV || {};
(function() {
    "use strict";

    // ── State ──
    var v = null;           // 3Dmol viewer instance
    var molModel = null;    // current molecule model

    const QCVIZ_ESP_PRESETS = %%ESP_PRESETS_JSON%%;
    const QCVIZ_ESP_PRESET_ORDER = ["rwb", "viridis", "inferno", "spectral", "nature", "acs", "rsc", "matdark", "grey", "hicon"];

    let qcvizCachedEDenVol = null;
    let qcvizCachedEPotVol = null;
    let qcvizCachedEDenKey = null;
    let qcvizCachedEPotKey = null;
    const qcvizCachedOrbVols = new Map();

    let qcvizEspSurfaceId = null;
    let qcvizOrbSurfaceIds = [];

    function qcvizGetViewer() {
      if (typeof v !== "undefined" && v) return v;
      if (typeof viewer !== "undefined" && viewer) return viewer;
      return null;
    }

    function qcvizNormalizeB64(s) {
      s = String(s || "").trim().replace(/\\s+/g, "").replace(/-/g, "+").replace(/_/g, "/");
      const pad = s.length % 4;
      if (pad) s += "=".repeat(4 - pad);
      return s;
    }

    function qcvizDecodeB64Text(b64) {
      try {
        const normalized = qcvizNormalizeB64(b64);
        const raw = atob(normalized);
        if (typeof TextDecoder === "undefined") return raw;
        const bytes = new Uint8Array(raw.length);
        for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
        return new TextDecoder("utf-8", { fatal: false }).decode(bytes);
      } catch (err) {
        console.error("[QCViz] Base64 decode failed:", err);
        return null;
      }
    }

    function qcvizSetDashboardStatus(msg, isError) {
      const el = document.getElementById("status-text");
      if (el) {
        el.textContent = msg;
        el.style.color = isError ? "#b91c1c" : "";
      }
    }

    function qcvizSafeRender() {
      try {
        const vv = qcvizGetViewer();
        if (vv && typeof vv.render === "function") vv.render();
      } catch (err) {
        console.error("[QCViz] viewer.render() failed:", err);
      }
    }

    function qcvizSafeRemoveSurface(surfaceId) {
      if (surfaceId == null) return null;
      try {
        const vv = qcvizGetViewer();
        if (vv && typeof vv.removeShape === "function") {
          vv.removeShape(surfaceId);
        }
      } catch (err) {
        console.warn("[QCViz] removeShape failed:", err);
      }
      return null;
    }

    function qcvizSafeRemoveSurfaceList(ids) {
      if (!Array.isArray(ids)) return [];
      for (const id of ids) qcvizSafeRemoveSurface(id);
      return [];
    }

    function qcvizMakeVolumeDataFromB64(b64, format, label) {
      const text = qcvizDecodeB64Text(b64);
      if (!text) {
        throw new Error(label + " decode returned empty/null text");
      }
      try {
        return new $3Dmol.VolumeData(text, format);
      } catch (err) {
        console.error("[QCViz] VolumeData creation failed for " + label + ":", err);
        throw new Error(label + " VolumeData creation failed: " + (err && err.message ? err.message : err));
      }
    }

    function qcvizGetCachedCube(kind, b64) {
      if (kind === "eden") {
        if (!qcvizCachedEDenVol || qcvizCachedEDenKey !== b64) {
          qcvizCachedEDenVol = qcvizMakeVolumeDataFromB64(b64, "cube", "electron density cube");
          qcvizCachedEDenKey = b64;
        }
        return qcvizCachedEDenVol;
      }
      if (kind === "epot") {
        if (!qcvizCachedEPotVol || qcvizCachedEPotKey !== b64) {
          qcvizCachedEPotVol = qcvizMakeVolumeDataFromB64(b64, "cube", "electrostatic potential cube");
          qcvizCachedEPotKey = b64;
        }
        return qcvizCachedEPotVol;
      }
      throw new Error("Unknown cube cache type: " + kind);
    }

    function qcvizGetOrbitalVolume(idx) {
      const b64 = orbCubes[idx] ? orbCubes[idx].b64 : null;
      if (!b64) throw new Error("Missing orbital cube at index " + idx);
      const cached = qcvizCachedOrbVols.get(idx);
      if (cached && cached.b64 === b64) return cached.vol;
      const vol = qcvizMakeVolumeDataFromB64(b64, "cube", "orbital cube #" + idx);
      qcvizCachedOrbVols.set(idx, { b64, vol });
      return vol;
    }

    function qcvizSyncEspSelectOptions() {
      const sel = document.getElementById("sel-esp");
      if (!sel || !QCVIZ_ESP_PRESETS) return;
      const current = sel.value || "rwb";
      sel.innerHTML = "";
      const orderedKeys = [];
      const seen = new Set();
      for (const key of QCVIZ_ESP_PRESET_ORDER) {
        if (QCVIZ_ESP_PRESETS[key] && !seen.has(key)) { orderedKeys.push(key); seen.add(key); }
      }
      for (const key of Object.keys(QCVIZ_ESP_PRESETS)) {
        if (!seen.has(key)) { orderedKeys.push(key); seen.add(key); }
      }
      for (const key of orderedKeys) {
        const opt = document.createElement("option");
        opt.value = key;
        opt.textContent = QCVIZ_ESP_PRESETS[key].name || key;
        if (key === current) opt.selected = true;
        sel.appendChild(opt);
      }
    }

    function qcvizResolveEspVolscheme(presetName, vmin, vmax) {
      try {
        var p = QCVIZ_ESP_PRESETS[presetName];
        if (p && p.gradient_type === "linear" && p.colors) {
            return new $3Dmol.Gradient.CustomLinear(vmin, vmax, p.colors);
        }
      } catch (err) { console.warn("[QCViz] custom ESP scheme builder failed:", err); }
      return new $3Dmol.Gradient.RWB(vmin, vmax);
    }

    var currentOrb = -1;    // currently displayed orbital index
    var orbSurfaces = [];   // references to orbital isosurfaces
    var espSurface = null;  // reference to ESP surface
    var labelsVisible = false;

    // Cached VolumeData objects to avoid re-parsing on every slider change
    var cachedOrbVolData = null;   // VolumeData for current orbital cube
    var cachedOrbIdx     = -1;     // which orbital index the cache belongs to
    var cachedEDenVol    = null;   // VolumeData for electron density
    var cachedEPotVol    = null;   // VolumeData for electrostatic potential

    // ── Configuration (injected by Python backend) ──
    var xyzB64       = "%%XYZ_B64%%";
    var orbCubes     = %%ORB_JSON%%;
    var presetsData  = %%ESP_PRESETS_DATA%%;
    var wikiQ        = %%WIKI_QUERY%%;
    var chargeVals   = %%CHARGES_VAL_JSON%%;
    var atomLabels   = %%ATOM_LABELS_JSON%%;
    var eDenB64      = "%%EDEN_B64%%";
    var ePotB64      = "%%EPOT_B64%%";
    var eMinOrig     = parseFloat("%%EMIN%%") || -0.05;
    var eMaxOrig     = parseFloat("%%EMAX%%") || 0.05;

    // ★ FIX ESP #1: Validate BOTH density AND potential data exist
    var hasESP = (
        typeof eDenB64 === "string" && eDenB64.length > 10 &&
        typeof ePotB64 === "string" && ePotB64.length > 10
    );

    var S = {
        // Orbital-specific controls
        orbIso: 0.02,
        orbOpa: 0.8,
        // ESP-specific controls
        espIso: 0.002,
        espOpa: 0.8,
        // General state
        esp: false,
        espP: "rwb",
        wire: false,
        focus: false,
        locked: -1,
        labels: false,
        charges: false,
        spinning: false,
        espMin: eMinOrig,
        espMax: eMaxOrig
    };

    var lblHandles = { atoms: [], charges: [] };

    // ── Debounce guard for heavy renders ──
    var _refreshTimer = null;
    function debouncedRefresh(fn, delay) {
        if (_refreshTimer) clearTimeout(_refreshTimer);
        _refreshTimer = setTimeout(function() {
            _refreshTimer = null;
            fn();
        }, delay || 60);
    }

    function ensureESPVolumes() {
        if (!hasESP) return false;
        try {
            if (!espDenVolume) {
                var denStr = D(eDenB64);
                if (!denStr || denStr.length < 10) {
                    hasESP = false;
                    return false;
                }
                espDenVolume = new $3Dmol.VolumeData(denStr, "cube");
            }
            if (!espPotVolume) {
                var potStr = D(ePotB64);
                if (!potStr || potStr.length < 10) {
                    hasESP = false;
                    return false;
                }
                espPotVolume = new $3Dmol.VolumeData(potStr, "cube");
            }
            return true;
        } catch(e) {
            console.error("[QCViz] ESP volume data creation failed:", e);
            hasESP = false;
            return false;
        }
    }

    // ── UTILITIES ──
    function safe3D(fn) { try { fn(); } catch(e) { console.warn("[QCViz]", e); } }

    function D(b) {
        if (!b || typeof b !== "string" || b.length < 2) return "";
        try {
            var s = atob(b.replace(/\\s/g, ''));
            var n = s.length;
            var u = new Uint8Array(n);
            for (var i = 0; i < n; i++) u[i] = s.charCodeAt(i);
            return new TextDecoder("utf-8").decode(u);
        } catch(e) {
            console.error("[QCViz] Base64 decode failed:", e);
            return "";
        }
    }

    function makeGradient(pk, mn, mx) {
        var p = (presetsData && presetsData[pk]) ? presetsData[pk] : null;
        if (!p) {
            return new $3Dmol.Gradient.RWB(mn, mx);
        }
        if (p.gradient_type === "rwb") return new $3Dmol.Gradient.RWB(mn, mx);
        if (p.colors && p.colors.length > 0) {
            return new $3Dmol.Gradient.CustomLinear(mn, mx, p.colors);
        }
        return new $3Dmol.Gradient.RWB(mn, mx);
    }

    function updateStatus(msg) {
        var el = document.getElementById("status-text");
        if (el) el.textContent = msg;
    }

    function widenClipping(factor) {
        try {
            if (v && typeof v.getPerceivedDistance === "function") {
                var slab = v.getPerceivedDistance() * (factor || 3.0);
                v.setSlab(-slab, slab);
            }
        } catch(e) { }
    }

    // ── Isovalue mapping helpers ──
    // Orbital: quadratic map  slider [0..100] → iso [0.001 .. 0.100]
    function sliderToOrbIso(val) {
        return 0.001 + Math.pow(val / 100, 2) * 0.099;
    }
    function orbIsoToSlider(iso) {
        return Math.sqrt((iso - 0.001) / 0.099) * 100;
    }
    // ESP Density: quadratic map  slider [0..100] → iso [0.0001 .. 0.020]
    function sliderToEspIso(val) {
        return 0.0001 + Math.pow(val / 100, 2) * 0.0199;
    }
    function espIsoToSlider(iso) {
        return Math.sqrt((iso - 0.0001) / 0.0199) * 100;
    }

    // ── Viewer Initialization ──
    function initViewer() {
        var c = document.getElementById("v3d");
        if (!c) { console.error("[QCViz] #v3d element not found"); return; }

        if (c.offsetWidth < 10 || c.offsetHeight < 10) {
            console.log("[QCViz] viewer container not ready, retrying in 200ms...");
            setTimeout(initViewer, 200);
            return;
        }

        try {
            v = $3Dmol.createViewer(c, {
                backgroundColor: "white",
                antialias: true,
                disableFog: false
            });
        } catch(e) {
            console.error("[QCViz] Failed to create 3Dmol viewer:", e);
            return;
        }

        if (xyzB64) {
            var xyzStr = D(xyzB64);
            if (xyzStr) {
                molModel = v.addModel(xyzStr, "xyz");
            }
        }

        applyStyle("ballstick");

        v.zoomTo();
        v.zoom(0.85);
        widenClipping(2.5);
        v.render();

        window.addEventListener("resize", function() {
            if (v) {
                try { v.resize(); v.render(); } catch(e) {}
            }
        });

        console.log("[QCViz] Viewer initialized successfully.");
        updateStatus("Ready");

        if (orbCubes && orbCubes.length > 0) {
            showOrb(0);
            var orbIsoSlider = document.getElementById("orb-iso-slider");
            if (orbIsoSlider) {
                orbIsoSlider.value = orbIsoToSlider(S.orbIso);
            }
        }

        if (hasESP) {
            setTimeout(function() {
                ensureESPVolumes();
            }, 500);
        }

        var btnEsp = document.getElementById("btn-esp");
        if (btnEsp) {
            if (!hasESP) {
                btnEsp.disabled = true;
                btnEsp.style.opacity = "0.4";
                btnEsp.title = "ESP data not available";
            } else {
                btnEsp.disabled = false;
                btnEsp.style.opacity = "1";
                btnEsp.title = "Toggle ESP Surface (E)";
            }
        }

        if (wikiQ) {
            fetch("https://en.wikipedia.org/api/rest_v1/page/summary/" + encodeURIComponent(wikiQ))
                .then(function(r) { return r.json(); })
                .then(function(d) {
                    var el = document.getElementById("wC");
                    if (el) el.innerHTML = d.extract || "No abstract available.";
                })
                .catch(function(e) {
                    console.warn("[QCViz] Wiki fetch failed", e);
                    var el = document.getElementById("wC");
                    if (el) el.innerHTML = "Wikipedia fetch failed.";
                });
        } else {
            var el = document.getElementById("wC");
            if (el) el.innerHTML = "No Wikipedia data found.";
        }
    }

    // ── Molecule Display Styles ──
    function applyStyle(mode) {
        if (!v || !molModel) return;
        v.setStyle({}, {});

        switch(mode) {
            case "ballstick":
                v.setStyle({}, {
                    stick: { radius: 0.14, colorscheme: "Jmol" },
                    sphere: { scale: 0.28, colorscheme: "Jmol" }
                });
                break;
            case "stick":
                v.setStyle({}, {
                    stick: { radius: 0.15, colorscheme: "Jmol" }
                });
                break;
            case "sphere":
                v.setStyle({}, {
                    sphere: { scale: 0.6, colorscheme: "Jmol" }
                });
                break;
            case "wireframe":
                v.setStyle({}, {
                    line: { colorscheme: "Jmol" }
                });
                break;
            default:
                v.setStyle({}, {
                    stick: { radius: 0.14, colorscheme: "Jmol" },
                    sphere: { scale: 0.28, colorscheme: "Jmol" }
                });
        }

        if (S.locked >= 0) {
            v.setStyle({serial: S.locked}, {
                sphere: { scale: 0.5, color: "yellow", opacity: 0.6 },
                stick: { radius: 0.12, colorscheme: "Jmol" }
            });
        }
        v.render();
    }
    QV.applyStyle = applyStyle;

    // ── Orbital Rendering ──
    function clearOrbitals() {
        if (!v) return;
        for (var i = 0; i < orbSurfaces.length; i++) {
            try { v.removeShape(orbSurfaces[i]); } catch(e) {}
        }
        orbSurfaces = [];
    }

    function showOrb(idx) {
      currentOrb = idx;
      qcvizOrbSurfaceIds = qcvizSafeRemoveSurfaceList(qcvizOrbSurfaceIds);
      if (idx < 0) {
          qcvizSafeRender();
          return;
      }

      let vol;
      try {
        vol = qcvizGetOrbitalVolume(idx);
      } catch (err) {
        console.error("[QCViz] Orbital preparation failed:", err);
        return;
      }

      try {
        qcvizOrbSurfaceIds.push(
          v.addIsosurface(vol, {
            isoval: S.orbIso,
            color: "blue",
            opacity: S.orbOpa,
            smoothness: 1
          })
        );
        qcvizOrbSurfaceIds.push(
          v.addIsosurface(vol, {
            isoval: -S.orbIso,
            color: "red",
            opacity: S.orbOpa,
            smoothness: 1
          })
        );
        qcvizSafeRender();
        updateStatus("Orbital: " + (orbCubes[idx].label || idx));
      } catch (err) {
        console.error("[QCViz] showOrb failed:", err);
      }
    }
    QV.showOrb = showOrb;

    function refreshOrbSurfaces() {
      try {
        const sel = document.getElementById("sel-orb");
        const idx = sel ? Number(sel.value) : 0;

        if (!Number.isFinite(idx) || idx < 0) {
          qcvizSetDashboardStatus("Invalid orbital selection.", true);
          return;
        }

        showOrb(idx);
      } catch (err) {
        console.error("[QCViz] refreshOrbSurfaces failed:", err);
        qcvizSetDashboardStatus("Orbital refresh failed: " + (err && err.message ? err.message : err), true);
      }
    }

    function refreshESPSurface() {
        if (!v || !hasESP || !S.esp) return;
        clearESP();

        if (!espDenVolume) espDenVolume = new $3Dmol.VolumeData(D(eDenB64), "cube");
        if (!espPotVolume) espPotVolume = new $3Dmol.VolumeData(D(ePotB64), "cube");

        var grad = makeGradient(S.espP, S.espMin, S.espMax);
        var spec = {
            isoval: S.espIso,
            voldata: espPotVolume,
            volscheme: grad,
            opacity: S.espOpa,
            smoothness: 7,
            wireframe: S.wire
        };

        if (S.focus && S.locked >= 0) {
            var fa = v.selectedAtoms({serial: S.locked});
            if (fa && fa.length > 0) { spec.coords = fa; spec.seldist = 4.0; }
        }

        try {
            espSurface = v.addIsosurface(espDenVolume, spec);
        } catch(e) {
            console.error("QCViz: Error refreshing ESP surface:", e);
        }
        v.render();
    }

    function refreshOrbOnly() {
        if (currentOrb >= 0) {
            debouncedRefresh(refreshOrbSurfaces);
        }
    }
    
    function refreshESPOnly() {
        if (S.esp) {
            debouncedRefresh(refreshESPSurface);
        }
    }

    function refreshOrb() {
        if (currentOrb >= 0) {
            debouncedRefresh(refreshOrbSurfaces);
        } else if (S.esp) {
            debouncedRefresh(refreshESPSurface);
        }
    }
    QV.refreshOrb = refreshOrb;

    // ── ESP Rendering ──
    function clearESP() {
        if (!v || !espSurface) return;
        try { v.removeShape(espSurface); } catch(e) {}
        espSurface = null;
    }

    function renderESP() {
      qcvizEspSurfaceId = qcvizSafeRemoveSurface(qcvizEspSurfaceId);
      if (!S.esp) {
          var cb = document.getElementById("cb-grad");
          if(cb) cb.style.display = "none";
          qcvizSafeRender();
          updateStatus("Ready");
          return;
      }

      if (!hasESP) {
        qcvizSetDashboardStatus("ESP data unavailable.", false);
        qcvizSafeRender();
        return;
      }

      let denVol, potVol;
      try {
        denVol = qcvizGetCachedCube("eden", eDenB64);
        potVol = qcvizGetCachedCube("epot", ePotB64);
      } catch (err) {
        console.error("[QCViz] ESP volume preparation failed:", err);
        qcvizSetDashboardStatus("ESP decode failed", true);
        return;
      }

      try {
        const presetName = S.espP || "rwb";
        const iso = S.espIso || 0.002;
        const opacity = S.espOpa || 0.8;
        const vmin = S.espMin;
        const vmax = S.espMax;

        const volscheme = qcvizResolveEspVolscheme(presetName, vmin, vmax);

        qcvizEspSurfaceId = v.addIsosurface(denVol, {
          isoval: iso,
          opacity: opacity,
          smoothness: 1,
          voldata: potVol,
          volscheme: volscheme
        });

        var p = presetsData[presetName] || presetsData["rwb"];
        var cols = (p.gradient_type === "rwb") ? ["#3b82f6", "#ffffff", "#ef4444"] : p.colors;
        var cb = document.getElementById("cb-grad");
        if(cb) {
            cb.style.background = "linear-gradient(to right, " + cols.join(",") + ")";
            cb.style.display = "block";
        }

        qcvizSafeRender();
        updateStatus("ESP Surface");
      } catch (err) {
        console.error("[QCViz] renderESP failed:", err);
        qcvizSetDashboardStatus("ESP render failed", true);
      }
    }
    QV.renderESP = renderESP;

    // ── Labels ──
    function toggleLabels() {
        if (!v) return;
        S.labels = !S.labels;
        lblHandles.atoms.forEach(function(l) { safe3D(function(){ v.removeLabel(l); }); });
        lblHandles.atoms = [];

        if (S.labels && atomLabels && atomLabels.length > 0) {
            safe3D(function() {
                var allAtoms = v.selectedAtoms({});
                for (var i = 0; i < allAtoms.length && i < atomLabels.length; i++) {
                    if (atomLabels[i]) {
                        var l = v.addLabel(atomLabels[i], {
                            position: allAtoms[i],
                            fontSize: 11,
                            fontColor: "#1a1a2e",
                            backgroundColor: "rgba(255,255,255,0.85)",
                            borderColor: "#e2e6ec",
                            borderThickness: 1,
                            backgroundOpacity: 0.85,
                            showBackground: true,
                            alignment: "center"
                        });
                        lblHandles.atoms.push(l);
                    }
                }
            });
        }
        var btn = document.getElementById("btn-labels");
        if (btn) btn.classList.toggle("active", S.labels);
        v.render();
    }
    QV.toggleLabels = toggleLabels;

    function toggleCharges() {
        if (!v) return;
        S.charges = !S.charges;
        lblHandles.charges.forEach(function(l) { safe3D(function(){ v.removeLabel(l); }); });
        lblHandles.charges = [];

        if (S.charges && chargeVals && chargeVals.length > 0) {
            safe3D(function() {
                var allAtoms = v.selectedAtoms({});
                for (var i = 0; i < allAtoms.length && i < chargeVals.length; i++) {
                    if (chargeVals[i] !== undefined && chargeVals[i] !== null) {
                        var val = chargeVals[i];
                        var cStr = (val >= 0 ? "+" : "") + val.toFixed(3);
                        var cCol = val >= 0 ? "#dc2626" : "#2563eb";
                        var l = v.addLabel(cStr, {
                            position: allAtoms[i],
                            fontSize: 11,
                            fontColor: cCol,
                            backgroundColor: "rgba(255,255,255,0.9)",
                            backgroundOpacity: 0.9,
                            borderRadius: 4,
                            padding: 2,
                            yOffset: -1.5
                        });
                        lblHandles.charges.push(l);
                    }
                }
            });
        }
        var btn = document.getElementById("btn-charges");
        if (btn) btn.classList.toggle("active", S.charges);
        v.render();
    }
    QV.toggleCharges = toggleCharges;

    QV.lockAtom = function(i) {
        S.locked = (S.locked === i) ? -1 : i;
        var activeStyleBtn = document.querySelector(".toolbar button.active[data-style]");
        applyStyle(activeStyleBtn ? activeStyleBtn.getAttribute("data-style") : "ballstick");

        var rows = document.querySelectorAll(".charge-row");
        for (var j = 0; j < rows.length; j++) {
            if (parseInt(rows[j].getAttribute("data-idx")) === S.locked) {
                rows[j].classList.add("active");
            } else {
                rows[j].classList.remove("active");
            }
        }

        if (S.esp && S.focus) renderESP();
    };

    // ── Screenshot ──
    function captureScreenshot() {
        if (!v) return;
        try {
            var png = v.pngURI();
            var link = document.createElement("a");
            link.download = "qcviz_capture.png";
            link.href = png;
            link.click();
        } catch(e) {
            console.error("[QCViz] Screenshot failed:", e);
        }
    }
    QV.captureScreenshot = captureScreenshot;

    // ── Reset View ──
    function resetView() {
        if (!v) return;
        clearOrbitals();
        clearESP();
        currentOrb = -1;
        cachedOrbVolData = null;
        cachedOrbIdx = -1;
        S.esp = false;

        var espBtn = document.getElementById("btn-esp");
        if (espBtn) espBtn.classList.remove("active");

        S.labels = false;
        lblHandles.atoms.forEach(function(l) { safe3D(function(){ v.removeLabel(l); }); });
        lblHandles.atoms = [];
        var btnLbl = document.getElementById("btn-labels");
        if (btnLbl) btnLbl.classList.remove("active");

        S.charges = false;
        lblHandles.charges.forEach(function(l) { safe3D(function(){ v.removeLabel(l); }); });
        lblHandles.charges = [];
        var btnChg = document.getElementById("btn-charges");
        if (btnChg) btnChg.classList.remove("active");

        S.locked = -1;
        var rows = document.querySelectorAll(".charge-row");
        for (var j = 0; j < rows.length; j++) rows[j].classList.remove("active");

        // Reset sliders
        S.orbIso = 0.02;  S.orbOpa = 0.8;
        S.espIso = 0.002;  S.espOpa = 0.8;

        var orbIsoSl = document.getElementById("orb-iso-slider");
        var orbIsoVl = document.getElementById("orb-iso-val");
        if (orbIsoSl) orbIsoSl.value = orbIsoToSlider(S.orbIso);
        if (orbIsoVl) orbIsoVl.textContent = S.orbIso.toFixed(3);

        var orbOpaSl = document.getElementById("orb-opa-slider");
        var orbOpaVl = document.getElementById("orb-opa-val");
        if (orbOpaSl) orbOpaSl.value = S.orbOpa;
        if (orbOpaVl) orbOpaVl.textContent = S.orbOpa.toFixed(2);

        var espIsoSl = document.getElementById("esp-iso-slider");
        var espIsoVl = document.getElementById("esp-iso-val");
        if (espIsoSl) espIsoSl.value = espIsoToSlider(S.espIso);
        if (espIsoVl) espIsoVl.textContent = S.espIso.toFixed(4);

        var espOpaSl = document.getElementById("esp-opa-slider");
        var espOpaVl = document.getElementById("esp-opa-val");
        if (espOpaSl) espOpaSl.value = S.espOpa;
        if (espOpaVl) espOpaVl.textContent = S.espOpa.toFixed(2);

        applyStyle("ballstick");
        v.zoomTo();
        v.zoom(0.85);
        widenClipping(2.5);
        v.render();
        updateOrbListUI(-1);
        updateStatus("Ready");
    }
    QV.resetView = resetView;

    // ── Orbital List UI ──
    function updateOrbListUI(activeIdx) {
        var items = document.querySelectorAll(".orb-list li");
        for (var i = 0; i < items.length; i++) {
            if (parseInt(items[i].getAttribute("data-idx")) === activeIdx) {
                items[i].classList.add("active");
            } else {
                items[i].classList.remove("active");
            }
        }
    }

    // ── Boot Sequence ──
    function boot() {
        // Orbital Sliders
        var orbIsoSlider = document.getElementById("orb-iso-slider");
        var orbIsoVal    = document.getElementById("orb-iso-val");
        if (orbIsoSlider) {
            orbIsoSlider.addEventListener("input", function() {
                S.orbIso = sliderToOrbIso(parseFloat(this.value));
                if (orbIsoVal) orbIsoVal.textContent = S.orbIso.toFixed(3);
            });
            orbIsoSlider.addEventListener("change", function() {
                S.orbIso = sliderToOrbIso(parseFloat(this.value));
                if (orbIsoVal) orbIsoVal.textContent = S.orbIso.toFixed(3);
                refreshOrbOnly();
            });
        }

        var orbOpaSlider = document.getElementById("orb-opa-slider");
        var orbOpaVal    = document.getElementById("orb-opa-val");
        if (orbOpaSlider) {
            orbOpaSlider.addEventListener("input", function() {
                S.orbOpa = parseFloat(this.value);
                if (orbOpaVal) orbOpaVal.textContent = S.orbOpa.toFixed(2);
            });
            orbOpaSlider.addEventListener("change", function() {
                S.orbOpa = parseFloat(this.value);
                if (orbOpaVal) orbOpaVal.textContent = S.orbOpa.toFixed(2);
                refreshOrbOnly();
            });
        }

        // ESP Sliders
        var espIsoSlider = document.getElementById("esp-iso-slider");
        var espIsoVal    = document.getElementById("esp-iso-val");
        if (espIsoSlider) {
            espIsoSlider.addEventListener("input", function() {
                S.espIso = sliderToEspIso(parseFloat(this.value));
                if (espIsoVal) espIsoVal.textContent = S.espIso.toFixed(4);
            });
            espIsoSlider.addEventListener("change", function() {
                S.espIso = sliderToEspIso(parseFloat(this.value));
                if (espIsoVal) espIsoVal.textContent = S.espIso.toFixed(4);
                refreshESPOnly();
            });
        }

        var espOpaSlider = document.getElementById("esp-opa-slider");
        var espOpaVal    = document.getElementById("esp-opa-val");
        if (espOpaSlider) {
            espOpaSlider.addEventListener("input", function() {
                S.espOpa = parseFloat(this.value);
                if (espOpaVal) espOpaVal.textContent = S.espOpa.toFixed(2);
            });
            espOpaSlider.addEventListener("change", function() {
                S.espOpa = parseFloat(this.value);
                if (espOpaVal) espOpaVal.textContent = S.espOpa.toFixed(2);
                refreshESPOnly();
            });
        }

        // Style buttons
        document.querySelectorAll("[data-style]").forEach(function(btn) {
            btn.addEventListener("click", function() {
                document.querySelectorAll("[data-style]").forEach(function(b) { b.classList.remove("active"); });
                this.classList.add("active");
                applyStyle(this.getAttribute("data-style"));
            });
        });

        // Feature toggles
        var btnLabels = document.getElementById("btn-labels");
        if (btnLabels) btnLabels.addEventListener("click", toggleLabels);

        var btnCharges = document.getElementById("btn-charges");
        if (btnCharges) btnCharges.addEventListener("click", toggleCharges);

        var btnEsp = document.getElementById("btn-esp");
        if (btnEsp) {
            btnEsp.addEventListener("click", function() {
                if (!hasESP) {
                    updateStatus("ESP data not available");
                    return;
                }
                S.esp = !S.esp;
                this.classList.toggle("active", S.esp);
                renderESP();
            });
        }

        var selEsp = document.getElementById("sel-esp");
        if (selEsp) {
            selEsp.addEventListener("change", function(e) {
                S.espP = e.target.value;
                if (S.esp) renderESP();
            });
        }
        
        var btnWire = document.getElementById("btn-wire");
        if (btnWire) {
            btnWire.addEventListener("click", function() {
                S.wire = !S.wire;
                this.classList.toggle("active", S.wire);
                if (S.esp) renderESP();
            });
        }
        
        var btnFocus = document.getElementById("btn-focus");
        if (btnFocus) {
            btnFocus.addEventListener("click", function() {
                S.focus = !S.focus;
                this.classList.toggle("active", S.focus);
                if (S.esp) renderESP();
            });
        }

        var btnScreenshot = document.getElementById("btn-screenshot");
        if (btnScreenshot) btnScreenshot.addEventListener("click", QV.captureScreenshot);

        var btnReset = document.getElementById("btn-reset");
        if (btnReset) btnReset.addEventListener("click", QV.resetView);

        if (typeof requestAnimationFrame === "function") {
            requestAnimationFrame(function() {
                setTimeout(initViewer, 200);
            });
        } else {
            setTimeout(initViewer, 300);
        }

        document.addEventListener("keydown", function(e) {
            if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT") return;
            var key = e.key.toLowerCase();
            if (e.key === "Escape") { resetView(); }
            if (e.key >= "1" && e.key <= "9") {
                var idx = parseInt(e.key) - 1;
                if (idx < orbCubes.length) showOrb(idx);
            }
            if (key === "e" && btnEsp) btnEsp.click();
            if (key === "r") resetView();
            if (key === "l") toggleLabels();
            if (key === "c") toggleCharges();
        });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", boot);
    } else {
        boot();
    }

})();
</script>
"""

_DASHBOARD_HTML = """\
<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
        <title>QCViz Pro | %%MOL_NAME%%</title>
    <!-- Fonts -->
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">

    <!-- Icons -->
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@tabler/icons-webfont@latest/tabler-icons.min.css">
    <script src="https://3Dmol.org/build/3Dmol-min.js"></script>
    %%CSS%%
  </head>
  <body>
    <div class="layout-container">
      <div class="main-area">
        <!-- Top toolbar bar -->
        <div class="top-bar">
          <div class="logo-area">
            <div class="logo-icon">Q</div>
            QCViz-MCP <span class="badge">Enterprise v3.5</span>
          </div>
          <div class="toolbar">
            <button data-style="ballstick" class="active">
              Ball &amp; Stick
            </button>
            <button data-style="stick">Stick</button>
            <button data-style="sphere">Sphere</button>
            <button data-style="wireframe" id="btn-wire">Wire</button>
            <button data-style="focus" id="btn-focus">Focus</button>
            <button id="btn-labels">Labels</button>
            <button id="btn-charges">Charges</button>
            <button id="btn-esp">ESP</button>
            <button id="btn-screenshot">📷 Capture</button>
            <button id="btn-reset">Reset</button>
          </div>
        </div>

        <!-- Content: sidebar + viewer -->
        <div class="content-row">
          <div class="sidebar">
            <div class="sidebar-header">
              <h3>Orbital Explorer</h3>
            </div>
            <div class="sidebar-scroll">
              <!-- Molecule Info -->
              <div class="panel">
                <div class="panel-title">
                  <span class="icon">📋</span> Molecule Info
                </div>
                <div class="info-grid">
                  <span class="info-label">Formula</span
                  ><span class="info-value">%%FORMULA%%</span>
                  <span class="info-label">Method</span
                  ><span class="info-value">%%METHOD%%</span>
                  <span class="info-label">Basis</span
                  ><span class="info-value">%%BASIS%%</span>
                  <span class="info-label">Energy</span
                  ><span class="info-value">%%ENERGY%% Ha</span>
                </div>
                <div class="wiki-box" id="wC">Loading Wikipedia...</div>
              </div>

              <!-- ============================================================
                             🌈 ESP Map Panel — with DEDICATED ESP sliders
                             ============================================================ -->
              <div class="panel">
                <div class="panel-title">
                  <span class="icon">🌈</span> ESP Map
                </div>
                <div class="slider-group">
                  <select
                    id="sel-esp"
                    style="width: 100%; padding: 4px; margin-bottom: 8px; border-radius: 4px; border: 1px solid #e2e6ec; outline: none;"
                  >
                    %%ESP_OPTIONS%%
                  </select>
                </div>
                <!-- ESP Isovalue Slider -->
                <div class="slider-group">
                  <label
                    >ESP Density Isovalue
                    <span class="val" id="esp-iso-val">0.0020</span></label
                  >
                  <input
                    type="range"
                    id="esp-iso-slider"
                    min="0"
                    max="100"
                    value="10"
                  />
                </div>
                <!-- ESP Opacity Slider -->
                <div class="slider-group">
                  <label
                    >ESP Opacity
                    <span class="val" id="esp-opa-val">0.80</span></label
                  >
                  <input
                    type="range"
                    id="esp-opa-slider"
                    min="0.1"
                    max="1.0"
                    step="0.05"
                    value="0.80"
                  />
                </div>
                <div
                  class="esp-colorbar"
                  id="cb-grad"
                  style="display:none;"
                ></div>
                <div class="esp-labels">
                  <span id="cb-min">%%EMIN%%</span><span>0</span
                  ><span id="cb-max">%%EMAX%%</span>
                </div>
              </div>

              <!-- ============================================================
                             🔬 Orbitals Panel — with DEDICATED Orbital sliders
                             ============================================================ -->
              <div class="panel">
                <div class="panel-title">
                  <span class="icon">🔬</span> Orbitals
                </div>
                <!-- Orbital Isovalue Slider -->
                <div class="slider-group">
                  <label
                    >Orbital Isovalue
                    <span class="val" id="orb-iso-val">0.020</span></label
                  >
                  <input
                    type="range"
                    id="orb-iso-slider"
                    min="0"
                    max="100"
                    value="30"
                  />
                </div>
                <!-- Orbital Opacity Slider -->
                <div class="slider-group">
                  <label
                    >Orbital Opacity
                    <span class="val" id="orb-opa-val">0.80</span></label
                  >
                  <input
                    type="range"
                    id="orb-opa-slider"
                    min="0.1"
                    max="1.0"
                    step="0.05"
                    value="0.80"
                  />
                </div>
                <ul class="orb-list">
                  %%ORB_LIST%%
                </ul>
              </div>

              <!-- Charges panel -->
              <div class="panel" style="margin-bottom: 0;">
                <div class="panel-title">
                  <span class="icon">⚡</span> IAO Charges
                </div>
                <div style="font-size:10px;color:#9ca3af;margin-bottom:8px;">
                  Click row to lock focus on atom
                </div>
                <div class="charge-list">%%CHARGE_BARS%%</div>
              </div>
            </div>
          </div>

          <!-- 3D Viewer -->
          <div class="viewer-area">
            <div class="viewer-container">
              <div id="v3d"></div>
              <div class="viewer-overlay">
                <!-- Optional floating controls -->
              </div>
            </div>
            <div class="status-bar">
              <div class="status-item">
                <span class="status-dot"></span>
                <span id="status-text">Initializing...</span>
              </div>
              <div class="status-item">
                %%MOL_NAME%% | %%METHOD%%/%%BASIS%% | %%ENERGY%% Ha
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
    %%JS%%
  </body>
</html>
"""

_SIMPLE_MOL = (
    '<!DOCTYPE html><html><head>'
    '<script src="https://3Dmol.org/build/3Dmol-min.js"></script>'
    '</head><body><div id="v" style="width:100vw;height:100vh"></div>'
    "<script>"
    'var v=$3Dmol.createViewer(document.getElementById("v"),'
    '{backgroundColor:"white"});'
    'v.addModel(atob("%%XYZ_B64%%"),"xyz");'
    "v.setStyle({},{stick:{}});v.zoomTo();v.render();"
    "</script></body></html>"
)

_SIMPLE_ORB = r"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <title>QCViz Orbital</title>
  <script src="https://3Dmol.org/build/3Dmol-min.js"></script>
</head>
<body style="margin:0;padding:0;background:#fff;">
  <div id="v" style="width:100vw;height:100vh"></div>
  <script>
    function qcvizNormalizeB64(s) {
      s = String(s || "").trim().replace(/\s+/g, "").replace(/-/g, "+").replace(/_/g, "/");
      const pad = s.length % 4;
      if (pad) s += "=".repeat(4 - pad);
      return s;
    }

    function qcvizDecodeB64Text(b64) {
      const normalized = qcvizNormalizeB64(b64);
      const raw = atob(normalized);
      if (typeof TextDecoder === "undefined") return raw;
      const bytes = new Uint8Array(raw.length);
      for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
      return new TextDecoder("utf-8", { fatal: false }).decode(bytes);
    }

    try {
      var v = $3Dmol.createViewer(document.getElementById("v"), { backgroundColor: "white" });
      v.addModel(qcvizDecodeB64Text("%%XYZ_B64%%"), "xyz");

      var cubeText = qcvizDecodeB64Text("%%CUBE_B64%%");
      var vol = new $3Dmol.VolumeData(cubeText, "cube");

      v.addIsosurface(vol, {
        isoval: 0.02,
        color: "blue",
        opacity: 0.85,
        smoothness: 1
      });

      v.addIsosurface(vol, {
        isoval: -0.02,
        color: "red",
        opacity: 0.85,
        smoothness: 1
      });

      v.zoomTo();
      v.render();
    } catch (err) {
      console.error("Orbital render failed:", err);
      document.body.innerHTML =
        '<div style="padding:16px;font:14px/1.5 monospace;color:#b91c1c;background:#fff1f2;">' +
        '<strong>Orbital render failed</strong><br>' +
        String(err && err.message ? err.message : err) +
        '</div>';
    }
  </script>
</body>
</html>
"""
