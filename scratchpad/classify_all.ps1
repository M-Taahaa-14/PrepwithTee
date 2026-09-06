Set-Location "E:\NexGen Tutors Topicals"
$python = ".\.venv\Scripts\python"
$log = "data\classify_all.log"
$sylls = @("0478","0580","0620","0625","2058","2059","2210","4024","5054","5070","9618","9702","9709")

"=== classify_all started $(Get-Date) ===" | Tee-Object -Append $log

foreach ($syl in $sylls) {
    "--- heuristic $syl ---" | Tee-Object -Append $log
    & $python -m pipeline.classify --syllabus $syl --backend heuristic 2>&1 | Tee-Object -Append $log
    "--- subtopics-only $syl ---" | Tee-Object -Append $log
    & $python -m pipeline.classify --syllabus $syl --backend heuristic --subtopics-only 2>&1 | Tee-Object -Append $log
}

"=== done $(Get-Date) ===" | Tee-Object -Append $log
Write-Host "All done. Log: $log"
