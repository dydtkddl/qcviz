$bundleRoot = "D:\20260305_양자화학시각화MCP서버구축\version03\docs\external_review\QCVIZ_MOLCHAT_CHATBOT_FLEXIBILITY_BUNDLE_2026-03-29"
$zipPath = "D:\20260305_양자화학시각화MCP서버구축\version03\docs\external_review\QCVIZ_MOLCHAT_CHATBOT_FLEXIBILITY_BUNDLE_2026-03-29.zip"

if (Test-Path $bundleRoot) {
    Remove-Item -Recurse -Force $bundleRoot
}
if (Test-Path $zipPath) {
    Remove-Item -Force $zipPath
}

New-Item -ItemType Directory -Force -Path $bundleRoot | Out-Null

$items = @(
    @{ src = "D:\20260305_양자화학시각화MCP서버구축\version03\DEEP_SCAN_REPORT_qcviz-mcp_2026-03-28.md"; dst = "qcviz\DEEP_SCAN_REPORT_qcviz-mcp_2026-03-28.md" },
    @{ src = "D:\20260305_양자화학시각화MCP서버구축\version03\docs\QCViz_MolChat_Final_Patch_Design_Report_2026-03-29.md"; dst = "qcviz\docs\QCViz_MolChat_Final_Patch_Design_Report_2026-03-29.md" },
    @{ src = "D:\20260305_양자화학시각화MCP서버구축\version03\docs\QCVIZ_CHAT_STATE_INTEGRITY_FIX_PROMPT_2026-03-29.md"; dst = "qcviz\docs\QCVIZ_CHAT_STATE_INTEGRITY_FIX_PROMPT_2026-03-29.md" },
    @{ src = "D:\20260305_양자화학시각화MCP서버구축\version03\docs\external_review\QCVIZ_MOLCHAT_CHATBOT_FLEXIBILITY_RESEARCH_PROMPT_2026-03-29.md"; dst = "prompt\QCVIZ_MOLCHAT_CHATBOT_FLEXIBILITY_RESEARCH_PROMPT_2026-03-29.md" },
    @{ src = "D:\20260305_양자화학시각화MCP서버구축\version03\src\qcviz_mcp\llm"; dst = "qcviz\src\qcviz_mcp\llm" },
    @{ src = "D:\20260305_양자화학시각화MCP서버구축\version03\src\qcviz_mcp\services\gemini_agent.py"; dst = "qcviz\src\qcviz_mcp\services\gemini_agent.py" },
    @{ src = "D:\20260305_양자화학시각화MCP서버구축\version03\src\qcviz_mcp\services\ko_aliases.py"; dst = "qcviz\src\qcviz_mcp\services\ko_aliases.py" },
    @{ src = "D:\20260305_양자화학시각화MCP서버구축\version03\src\qcviz_mcp\services\molchat_client.py"; dst = "qcviz\src\qcviz_mcp\services\molchat_client.py" },
    @{ src = "D:\20260305_양자화학시각화MCP서버구축\version03\src\qcviz_mcp\services\pubchem_client.py"; dst = "qcviz\src\qcviz_mcp\services\pubchem_client.py" },
    @{ src = "D:\20260305_양자화학시각화MCP서버구축\version03\src\qcviz_mcp\services\structure_resolver.py"; dst = "qcviz\src\qcviz_mcp\services\structure_resolver.py" },
    @{ src = "D:\20260305_양자화학시각화MCP서버구축\version03\src\qcviz_mcp\services\ion_pair_handler.py"; dst = "qcviz\src\qcviz_mcp\services\ion_pair_handler.py" },
    @{ src = "D:\20260305_양자화학시각화MCP서버구축\version03\src\qcviz_mcp\web\app.py"; dst = "qcviz\src\qcviz_mcp\web\app.py" },
    @{ src = "D:\20260305_양자화학시각화MCP서버구축\version03\src\qcviz_mcp\web\runtime_info.py"; dst = "qcviz\src\qcviz_mcp\web\runtime_info.py" },
    @{ src = "D:\20260305_양자화학시각화MCP서버구축\version03\src\qcviz_mcp\web\routes\chat.py"; dst = "qcviz\src\qcviz_mcp\web\routes\chat.py" },
    @{ src = "D:\20260305_양자화학시각화MCP서버구축\version03\src\qcviz_mcp\web\routes\compute.py"; dst = "qcviz\src\qcviz_mcp\web\routes\compute.py" },
    @{ src = "D:\20260305_양자화학시각화MCP서버구축\version03\src\qcviz_mcp\web\static\chat.js"; dst = "qcviz\src\qcviz_mcp\web\static\chat.js" },
    @{ src = "D:\20260305_양자화학시각화MCP서버구축\version03\src\qcviz_mcp\web\static\app.js"; dst = "qcviz\src\qcviz_mcp\web\static\app.js" },
    @{ src = "D:\20260305_양자화학시각화MCP서버구축\version03\src\qcviz_mcp\web\templates\index.html"; dst = "qcviz\src\qcviz_mcp\web\templates\index.html" },
    @{ src = "D:\20260305_양자화학시각화MCP서버구축\version03\tests\test_chat_api.py"; dst = "qcviz\tests\test_chat_api.py" },
    @{ src = "D:\20260305_양자화학시각화MCP서버구축\version03\tests\test_chat_playwright.py"; dst = "qcviz\tests\test_chat_playwright.py" },
    @{ src = "D:\20260305_양자화학시각화MCP서버구축\version03\tests\test_runtime_health.py"; dst = "qcviz\tests\test_runtime_health.py" },
    @{ src = "D:\20260305_양자화학시각화MCP서버구축\version03\tests\test_structure_extraction.py"; dst = "qcviz\tests\test_structure_extraction.py" },
    @{ src = "D:\20260305_양자화학시각화MCP서버구축\version03\tests\v3\integration\test_chat_routes.py"; dst = "qcviz\tests\v3\integration\test_chat_routes.py" },
    @{ src = "D:\20260305_양자화학시각화MCP서버구축\version03\tests\v3\unit\test_molchat_client.py"; dst = "qcviz\tests\v3\unit\test_molchat_client.py" },
    @{ src = "D:\20260305_양자화학시각화MCP서버구축\version03\tests\v3\unit\test_structure_resolver.py"; dst = "qcviz\tests\v3\unit\test_structure_resolver.py" },
    @{ src = "C:\Users\user\Desktop\molcaht\molchat\v3\DEEP_SCAN_REPORT_MolChat_v3_2026-03-28.md"; dst = "molchat\DEEP_SCAN_REPORT_MolChat_v3_2026-03-28.md" },
    @{ src = "C:\Users\user\Desktop\molcaht\molchat\v3\backend\app\main.py"; dst = "molchat\backend\app\main.py" },
    @{ src = "C:\Users\user\Desktop\molcaht\molchat\v3\backend\app\routers\__init__.py"; dst = "molchat\backend\app\routers\__init__.py" },
    @{ src = "C:\Users\user\Desktop\molcaht\molchat\v3\backend\app\routers\chat.py"; dst = "molchat\backend\app\routers\chat.py" },
    @{ src = "C:\Users\user\Desktop\molcaht\molchat\v3\backend\app\routers\molecules.py"; dst = "molchat\backend\app\routers\molecules.py" },
    @{ src = "C:\Users\user\Desktop\molcaht\molchat\v3\backend\app\schemas\chat.py"; dst = "molchat\backend\app\schemas\chat.py" },
    @{ src = "C:\Users\user\Desktop\molcaht\molchat\v3\backend\app\schemas\molecule.py"; dst = "molchat\backend\app\schemas\molecule.py" },
    @{ src = "C:\Users\user\Desktop\molcaht\molchat\v3\backend\app\services\molecule_engine\__init__.py"; dst = "molchat\backend\app\services\molecule_engine\__init__.py" },
    @{ src = "C:\Users\user\Desktop\molcaht\molchat\v3\backend\app\services\molecule_engine\orchestrator.py"; dst = "molchat\backend\app\services\molecule_engine\orchestrator.py" },
    @{ src = "C:\Users\user\Desktop\molcaht\molchat\v3\backend\app\services\molecule_engine\query_resolver.py"; dst = "molchat\backend\app\services\molecule_engine\query_resolver.py" },
    @{ src = "C:\Users\user\Desktop\molcaht\molchat\v3\backend\app\services\molecule_engine\pug_rest_resolver.py"; dst = "molchat\backend\app\services\molecule_engine\pug_rest_resolver.py" },
    @{ src = "C:\Users\user\Desktop\molcaht\molchat\v3\tests\test_molecule_interpret.py"; dst = "molchat\tests\test_molecule_interpret.py" }
)

foreach ($item in $items) {
    if (-not (Test-Path $item.src)) {
        continue
    }
    $dest = Join-Path $bundleRoot $item.dst
    $parent = Split-Path $dest -Parent
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    if ((Get-Item $item.src).PSIsContainer) {
        Copy-Item -Path $item.src -Destination $dest -Recurse -Force
    } else {
        Copy-Item -Path $item.src -Destination $dest -Force
    }
}

Compress-Archive -Path $bundleRoot -DestinationPath $zipPath -Force
Get-Item $zipPath | Select-Object FullName, Length
