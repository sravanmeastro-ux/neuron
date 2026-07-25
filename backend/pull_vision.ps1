# Auto-resume download of the NEURON vision model until it completes.
# Handles flaky connections by retrying; ollama resumes from where it left off.
$model = "qwen2.5vl:7b"
$attempt = 0
while ($true) {
    $have = (ollama list 2>$null | Select-String $model)
    if ($have) {
        Write-Output "DONE: $model is downloaded."
        break
    }
    $attempt++
    Write-Output "Attempt $attempt : pulling $model ..."
    ollama pull $model 2>&1 | Out-Null
    Start-Sleep -Seconds 5
}
