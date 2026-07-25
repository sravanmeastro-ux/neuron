# Auto-resume download of any Ollama model until it completes.
# Usage: powershell -File pull_model.ps1 -Model "qwen3:14b"
param([string]$Model = "qwen3:14b")

while ($true) {
    ollama pull $Model
    if ($LASTEXITCODE -eq 0) {
        Write-Output "DONE: $Model is downloaded."
        break
    }
    Write-Output "Pull interrupted, retrying in 5s..."
    Start-Sleep -Seconds 5
}
