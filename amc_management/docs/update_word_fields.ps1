# Open a .docx in Microsoft Word, update the table of contents and all fields (page numbers),
# save it and print pages / images. docx-js writes the TOC as a field that only Word fills in.
# Usage (PowerShell): .\update_word_fields.ps1 -Path ..\docs\AMC_User_Manual.docx
param([Parameter(Mandatory = $true)][string]$Path)
$full = (Resolve-Path $Path).Path
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
try {
    $doc = $word.Documents.Open($full, $false, $false)
    foreach ($toc in $doc.TablesOfContents) { $toc.Update() }
    $doc.Fields.Update() | Out-Null
    $doc.Save()
    "{0}: pages={1} images={2}" -f (Split-Path $full -Leaf), $doc.ComputeStatistics(2), $doc.InlineShapes.Count
    $doc.Close([ref]0)
} finally {
    $word.Quit()
}
