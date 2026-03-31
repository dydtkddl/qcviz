# QCViz + MolChat Core Bundle Reassembly

이 문서는 메일 전송 과정에서 `QCVIZ_MOLCHAT_CORE_BUNDLE_2026-03-30.zip`이 보안 정책에 의해 차단될 경우를 대비한 재조립 안내서다.

## 포함 파일

- `QCVIZ_MOLCHAT_CORE_BUNDLE_2026-03-30.zip.base64.part01.txt`
- `QCVIZ_MOLCHAT_CORE_BUNDLE_2026-03-30.zip.base64.part02.txt`
- `QCVIZ_MOLCHAT_CORE_BUNDLE_2026-03-30.zip.base64.part03.txt`
- `QCVIZ_MOLCHAT_CORE_BUNDLE_2026-03-30.zip.base64.part04.txt`
- `QCVIZ_MOLCHAT_CORE_BUNDLE_2026-03-30.zip.base64.part05.txt`
- `QCVIZ_MOLCHAT_CORE_BUNDLE_2026-03-30.zip.base64.part06.txt`

## 복원 방법

### PowerShell

```powershell
$parts = 1..6 | ForEach-Object {
    "QCVIZ_MOLCHAT_CORE_BUNDLE_2026-03-30.zip.base64.part{0:d2}.txt" -f $_
}
$joined = ($parts | ForEach-Object { Get-Content $_ -Raw }) -join ""
[IO.File]::WriteAllBytes(
    "QCVIZ_MOLCHAT_CORE_BUNDLE_2026-03-30.zip",
    [Convert]::FromBase64String($joined)
)
```

### Python

```python
from pathlib import Path
import base64

parts = [
    Path(f"QCVIZ_MOLCHAT_CORE_BUNDLE_2026-03-30.zip.base64.part{i:02d}.txt")
    for i in range(1, 7)
]
joined = "".join(p.read_text(encoding="utf-8") for p in parts)
Path("QCVIZ_MOLCHAT_CORE_BUNDLE_2026-03-30.zip").write_bytes(
    base64.b64decode(joined)
)
```

