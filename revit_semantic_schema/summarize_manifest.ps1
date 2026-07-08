<#
.SYNOPSIS
    Summarize a ground_truth_manifest_<version>.json without needing Python or re-uploading
    the whole file anywhere. Built-in cmdlets only (ConvertFrom-Json etc.) -- no dependencies.

.EXAMPLE
    .\summarize_manifest.ps1 -Path .\outputs\revit_2024\reflection\ground_truth_manifest_2024.json
#>
param(
    [Parameter(Mandatory = $true)]
    [string] $Path
)

Write-Host "Reading $Path ..."
$sw = [System.Diagnostics.Stopwatch]::StartNew()
$json = Get-Content -LiteralPath $Path -Raw
$manifest = $json | ConvertFrom-Json
Write-Host "Parsed in $([math]::Round($sw.Elapsed.TotalSeconds, 2))s"
Write-Host ""

Write-Host "=== Top-level ==="
Write-Host "revit_version:    $($manifest.revit_version)"
Write-Host "generated_at:     $($manifest.generated_at)"
Write-Host "namespace_prefix: $($manifest.namespace_prefix)"
Write-Host ""

Write-Host "=== Assemblies scanned ==="
Write-Host "Total scanned: $($manifest.assemblies_scanned.Count)"
$matched = @($manifest.assemblies_scanned | Where-Object { $_.matched })
Write-Host "Matched ($($matched.Count)):"
$matched | ForEach-Object { Write-Host "  $($_.name)" }
Write-Host ""

Write-Host "=== Types ==="
Write-Host "Total types: $($manifest.types.Count)"
$byKind = $manifest.types | Group-Object -Property kind | Sort-Object -Property Count -Descending
$byKind | ForEach-Object { Write-Host "  $($_.Name): $($_.Count)" }
Write-Host ""

Write-Host "=== Unresolved-reference sentinels (from the recent type/member guard fixes) ==="
$unresolvedBaseType = @($manifest.types | Where-Object { $_.base_type -eq "<unresolved>" })
$unresolvedChain = @($manifest.types | Where-Object { $_.inheritance_chain -contains "<unresolved>" })
$unresolvedIfaces = @($manifest.types | Where-Object { $_.implemented_interfaces -contains "<unresolved>" })
Write-Host "Types with unresolved base_type:              $($unresolvedBaseType.Count)"
Write-Host "Types with unresolved inheritance_chain entry: $($unresolvedChain.Count)"
Write-Host "Types with unresolved implemented_interfaces:  $($unresolvedIfaces.Count)"
if ($unresolvedIfaces.Count -gt 0) {
    Write-Host "  Sample (up to 5):"
    $unresolvedIfaces | Select-Object -First 5 | ForEach-Object { Write-Host "    $($_.full_type_name)" }
}
Write-Host ""

Write-Host "=== Members / signature shapes worth a glance ==="
$allMembers = $manifest.types | ForEach-Object { $_.members }
Write-Host "Total members across all types: $($allMembers.Count)"
$byRefParams = @($allMembers | ForEach-Object { $_.parameters } | Where-Object { $_.type -match '^(out|ref) ' })
Write-Host "Parameters detected as out/ref (canonicalized form): $($byRefParams.Count)"
if ($byRefParams.Count -gt 0) {
    Write-Host "  Sample (up to 5):"
    $byRefParams | Select-Object -First 5 -Unique | ForEach-Object { Write-Host "    $($_.type)" }
}
$voidReturns = @($allMembers | Where-Object { $null -eq $_.return_type -and $_.kind -eq 'method' })
Write-Host "Void-return methods (return_type: null): $($voidReturns.Count)"
Write-Host ""

Write-Host "=== Specific real-API facts this project has been tracking ==="
$room = $manifest.types | Where-Object { $_.full_type_name -like "*Architecture.Room" } | Select-Object -First 1
if ($room) {
    Write-Host "Room.inheritance_chain: $($room.inheritance_chain -join ' -> ')"
    Write-Host "Room's own members named Number: $(($room.members | Where-Object { $_.name -eq 'Number' }).Count)"
}
$spatial = $manifest.types | Where-Object { $_.full_type_name -eq "Autodesk.Revit.DB.SpatialElement" } | Select-Object -First 1
if ($spatial) {
    $numberMember = $spatial.members | Where-Object { $_.name -eq 'Number' } | Select-Object -First 1
    if ($numberMember) {
        Write-Host "SpatialElement.Number -> declaring_type=$($numberMember.declaring_type), return_type=$($numberMember.return_type)"
    }
}
$material = $manifest.types | Where-Object { $_.full_type_name -eq "Autodesk.Revit.DB.Material" } | Select-Object -First 1
if ($material) {
    $names = $material.members.name
    foreach ($candidate in @("SurfacePatternId", "CutPatternId", "CutBackgroundPatternId", "CutForegroundPatternId", "SurfaceBackgroundPatternId", "SurfaceForegroundPatternId")) {
        $found = if ($names -contains $candidate) { "FOUND" } else { "not found" }
        Write-Host "Material.$candidate : $found"
    }
}
$element = $manifest.types | Where-Object { $_.full_type_name -eq "Autodesk.Revit.DB.Element" } | Select-Object -First 1
if ($element) {
    $overloads = $element.members | Where-Object { $_.name -eq "ChangeTypeId" }
    Write-Host "Element.ChangeTypeId overloads: $($overloads.Count)"
    foreach ($o in $overloads) {
        $paramTypes = ($o.parameters | ForEach-Object { $_.type }) -join ', '
        Write-Host "  static=$($o.is_static) return=$($o.return_type) params=($paramTypes)"
    }
}
Write-Host ""

Write-Host "Done."
