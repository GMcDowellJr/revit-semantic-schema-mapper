#Requires -Version 5.1
<#
.SYNOPSIS
    Stage A of docs/dll_reflection_v0.md: reflects over already-compiled
    Autodesk.Revit.DB assemblies and emits ground_truth_manifest_<version>.json.

.DESCRIPTION
    Recursively enumerates every *.dll under -InstallDir, metadata-only-loads each one
    (never running a static initializer, never requiring Revit's unmanaged dependencies to
    resolve), keeps the assemblies that expose at least one type under -NamespacePrefix, and
    reflects each matched assembly's types/members into the JSON schema documented in
    docs/dll_reflection_v0.md ("Stage A: the reflection tool" -> "Manifest schema").

    Two hosts are supported, since which one is actually available on a given Windows/Revit
    machine should never be assumed (see docs/dll_reflection_v0.md's "Open questions"):

      - Windows PowerShell 5.1 ("Desktop" edition, .NET Framework): uses
        [System.Reflection.Assembly]::ReflectionOnlyLoadFrom, which is built in and needs no
        extra install. This is the primary, best-supported path, and the only one that has
        actually been exercised against real (non-Revit) DLLs so far -- see crawl_notes.md.
      - PowerShell 7+ ("Core" edition, .NET / .NET Core): uses
        System.Reflection.MetadataLoadContext, a separate NuGet package (not built in) --
        pass its path via -MetadataLoadContextAssembly. Confirmed working end-to-end against
        real (non-Revit) BCL assemblies in this project's own dev sandbox (a Linux box with
        no Windows/Revit access at all), but cross-framework resolution against Revit's real
        net48-targeted RevitAPI.dll has NOT been verified: MetadataLoadContext needs reference
        assemblies matching the *target* assembly's framework (mscorlib etc. for net48), not
        just the host runtime's own core assemblies -- pass a folder of those via
        -NetFrameworkReferenceAssembliesDir if this path is used against Revit. See
        crawl_notes.md for exactly what was and wasn't confirmed.

.PARAMETER InstallDir
    Root directory to recursively scan for *.dll (e.g. "C:\Program Files\Autodesk\Revit 2024").

.PARAMETER NamespacePrefix
    Only assemblies exposing at least one type under this namespace are kept. Default matches
    the existing docs crawler's own --namespace-prefix default/flag name for consistency.

.PARAMETER Out
    Path to write the manifest JSON to.

.PARAMETER RevitVersion
    Recorded in the manifest's "revit_version" field. If omitted, it's guessed from the last
    run of digits in -InstallDir's own folder name (e.g. "Revit 2024" -> "2024") -- an explicit,
    checkable guess, not a silent one: the script prints what it guessed and why.

.PARAMETER MetadataLoadContextAssembly
    Path to System.Reflection.MetadataLoadContext.dll (only needed/used on PowerShell 7+ /
    "Core" edition; ignored on Windows PowerShell 5.1 / "Desktop" edition, which has
    ReflectionOnlyLoadFrom built in).

.PARAMETER NetFrameworkReferenceAssembliesDir
    Only used on the Core/MetadataLoadContext path. Extra directory of reference assemblies
    (mscorlib.dll, System.dll, etc.) to seed the resolver with, needed because Revit's DLLs
    target .NET Framework while a PowerShell 7 host runs .NET/.NET Core -- the host's own core
    assemblies are a different framework and won't satisfy that resolution on their own.

.PARAMETER DotNetSharedFrameworkRoot
    Only used on the Desktop/ReflectionOnlyLoadFrom path. Root of an installed .NET (Core)
    runtime's shared-framework layout (default: "$env:ProgramFiles\dotnet\shared", i.e.
    `dotnet --list-runtimes`'s own install location) -- confirmed a real, large need on a
    live Revit 2025 run (see docs/crawl_notes.md): some Revit assemblies (AcDbMgd chief among
    them) are themselves built against modern .NET 5-8 (plus WPF-on-.NET-Core), not .NET
    Framework, and reference identities like "System.Runtime, Version=8.0.0.0, ..." that a
    classic .NET Framework GAC can never contain, at any version, regardless of what's under
    -InstallDir. If the matching .NET runtime (e.g. the .NET 8 Desktop Runtime, for
    Microsoft.NETCore.App's System.Runtime/System.Collections/etc. and
    Microsoft.WindowsDesktop.App's PresentationFramework/WindowsBase/System.Xaml) is installed
    on this machine, this lets the resolver find its real DLLs and load them purely for
    metadata -- ReflectionOnlyLoadFrom never executes a loaded assembly, so a modern .NET
    assembly loads here fine even though this whole process is old .NET Framework. If no
    matching runtime is installed at all, this can't manufacture the missing metadata --
    install the .NET runtime version(s) named in -Verbose's LoaderExceptions output first.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string] $InstallDir,

    [string] $NamespacePrefix = "Autodesk.Revit.DB",

    [Parameter(Mandatory = $true)]
    [string] $Out,

    [string] $RevitVersion,

    [string] $MetadataLoadContextAssembly,

    [string] $NetFrameworkReferenceAssembliesDir,

    [string] $DotNetSharedFrameworkRoot = (Join-Path $env:ProgramFiles "dotnet\shared")
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path -LiteralPath $InstallDir -PathType Container)) {
    throw "InstallDir not found or not a directory: $InstallDir"
}

if (-not $RevitVersion) {
    $folderName = Split-Path -Leaf ($InstallDir.TrimEnd('\', '/'))
    $m = [regex]::Match($folderName, '(\d{4})')
    if ($m.Success) {
        $RevitVersion = $m.Groups[1].Value
        Write-Verbose "RevitVersion not specified; guessed '$RevitVersion' from InstallDir folder name '$folderName'."
    } else {
        throw "Could not guess -RevitVersion from InstallDir folder name '$folderName'; pass -RevitVersion explicitly."
    }
}

# -Out must be a *file* path (e.g. "...\ground_truth_manifest_2024.json"), not a directory --
# confirmed on a real run that passing an existing directory produces a confusing low-level
# "Access to the path '...' is denied" from File.WriteAllText (Windows reports "can't create a
# file where a directory of the same name already exists" as access-denied, not a clearer
# error) rather than anything actionable. Fail with a clear message up front instead, and
# create -Out's parent directory if it's simply missing rather than requiring it to pre-exist.
if (Test-Path -LiteralPath $Out -PathType Container) {
    throw "-Out '$Out' is an existing directory, not a file path -- pass a file path to write " +
          "the manifest to, e.g. '$($Out.TrimEnd('\', '/'))\ground_truth_manifest_$RevitVersion.json'."
}
$outParent = Split-Path -Parent $Out
if ($outParent -and -not (Test-Path -LiteralPath $outParent -PathType Container)) {
    Write-Verbose "Creating -Out's parent directory: $outParent"
    New-Item -ItemType Directory -Path $outParent -Force | Out-Null
}

$isCore = $PSVersionTable.PSEdition -eq 'Core'
Write-Verbose "PowerShell host: $($PSVersionTable.PSEdition) $($PSVersionTable.PSVersion) -- using $(if ($isCore) { 'MetadataLoadContext' } else { 'ReflectionOnlyLoadFrom' })"


# -- shared: enumerate dlls ----------------------------------------------------

function Get-DllPaths([string] $Root) {
    Write-Verbose "Enumerating *.dll recursively under $Root ..."
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $paths = @(Get-ChildItem -LiteralPath $Root -Filter *.dll -Recurse -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty FullName)
    Write-Verbose "Found $($paths.Count) dlls in $([math]::Round($sw.Elapsed.TotalSeconds, 2))s"
    return $paths
}


# -- Desktop-path only: real .NET (Core) runtime files, for references that are never Framework/GAC --

function Get-DotNetSharedFrameworkIndex([string] $Root) {
    # Maps "<simpleName>|<majorVersion>" -> full path, for every *.dll under any
    # Microsoft.NETCore.App/Microsoft.WindowsDesktop.App/Microsoft.AspNetCore.App version
    # folder under $Root -- the standard `dotnet --list-runtimes` layout (e.g.
    # "...\dotnet\shared\Microsoft.NETCore.App\8.0.11\System.Runtime.dll"). Confirmed a real,
    # large need on a live Revit 2025 run (see docs/crawl_notes.md): 434 assemblies'
    # ReflectionTypeLoadExceptions all traced back to a handful of exact identities --
    # System.Runtime/PresentationFramework/WindowsBase/System.Xaml/netstandard/etc at various
    # .NET 5-8 versions -- none of which a classic Framework/GAC resolve can ever satisfy,
    # regardless of what's under -InstallDir, since they aren't Framework assemblies at all.
    # Only the *major* version is indexed, not the full patch version: an installed runtime's
    # own files keep AssemblyVersion pinned to "<major>.0.0.0" across every patch release
    # (confirmed Microsoft's own .NET versioning convention), so any installed patch folder for
    # a given major version satisfies a reference asking for that major version.
    $index = @{}
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) {
        Write-Verbose "DotNetSharedFrameworkRoot '$Root' not found -- a reference to a modern .NET runtime assembly (System.Runtime, PresentationFramework, ...) will stay unresolved unless the matching .NET runtime is installed and -DotNetSharedFrameworkRoot points at it."
        return $index
    }
    $appModelDirs = @("Microsoft.NETCore.App", "Microsoft.WindowsDesktop.App", "Microsoft.AspNetCore.App") |
        ForEach-Object { Join-Path $Root $_ } | Where-Object { Test-Path -LiteralPath $_ -PathType Container }
    foreach ($appModelDir in $appModelDirs) {
        Get-ChildItem -LiteralPath $appModelDir -Directory -ErrorAction SilentlyContinue | ForEach-Object {
            $major = ($_.Name -split '\.')[0]
            Get-ChildItem -LiteralPath $_.FullName -Filter *.dll -ErrorAction SilentlyContinue | ForEach-Object {
                $simpleName = [System.IO.Path]::GetFileNameWithoutExtension($_.Name)
                $key = "$simpleName|$major"
                if (-not $index.ContainsKey($key)) { $index[$key] = $_.FullName }
            }
        }
    }
    Write-Verbose "Indexed $($index.Count) (name, major version) dotnet shared-framework dll(s) under $Root"
    return $index
}


# -- shared: type/member -> manifest shape -------------------------------------
#
# Deliberately close to models.NodeCandidate/MemberInfo's shape -- see
# docs/dll_reflection_v0.md, "Manifest schema". Every conversion here reads real,
# asserted-by-the-compiler metadata (Type/PropertyInfo/MethodInfo), not a guess.

function Get-TypeKindString([Type] $Type) {
    if ($Type.IsEnum) { return "enum" }
    if ($Type.IsInterface) { return "interface" }
    if ($Type.IsValueType) { return "struct" }
    return "class"
}

function Get-BaseTypeName([Type] $Type) {
    # Type.BaseType's getter is what actually resolves the base type's own assembly -- if
    # that assembly is neither under -InstallDir nor loadable from the GAC, accessing this
    # throws instead of returning an "unresolved" marker. "<unresolved>" is a deliberately
    # distinguishable sentinel (never a real FullName, since real ones are dotted CLR names)
    # rather than $null, which would be indistinguishable from "genuinely has no base type".
    try {
        $base = $Type.BaseType
        if ($null -eq $base) { return $null }
        return $base.FullName
    } catch {
        Write-Verbose "Could not resolve base type of $($Type.FullName): $($_.Exception.Message)"
        return "<unresolved>"
    }
}

function Get-InheritanceChainNames([Type] $Type) {
    # Guards each .BaseType access individually (not the loop as a whole), since that's the
    # specific call that can throw for an ancestor whose own assembly can't be resolved --
    # confirmed a real risk on the live Revit 2024 run (see crawl_notes.md), the same
    # category of problem as the per-member guards in Convert-MembersToManifest below. On
    # failure, record "<unresolved>" as the chain's last entry (an explicit, checkable fact)
    # and stop walking further, rather than losing the whole type -- see Get-BaseTypeName's
    # comment on why "<unresolved>" and not $null/silently truncating.
    $chain = New-Object System.Collections.Generic.List[string]
    $cur = $Type
    while ($true) {
        $next = $null
        try {
            $next = $cur.BaseType
        } catch {
            Write-Verbose "Could not resolve further ancestor above $($cur.FullName) for $($Type.FullName): $($_.Exception.Message)"
            [void]$chain.Add("<unresolved>")
            break
        }
        if ($null -eq $next) { break }
        [void]$chain.Add($next.FullName)
        $cur = $next
    }
    return @($chain)
}

function Get-ImplementedInterfaceNames([Type] $Type) {
    # GetInterfaces() resolves every implemented interface's own assembly to build its
    # result; unlike Assembly.GetTypes() there's no partial-success form (no equivalent of
    # ReflectionTypeLoadException's .Types array) -- one unresolved interface fails the
    # whole call. Guarded the same way as Get-BaseTypeName above.
    try {
        return @($Type.GetInterfaces() | ForEach-Object { $_.FullName })
    } catch {
        Write-Verbose "Could not resolve implemented interfaces of $($Type.FullName): $($_.Exception.Message)"
        return @("<unresolved>")
    }
}

function Get-ReturnTypeString($ReturnType) {
    # A method with no return value reports "System.Void" from reflection; the manifest
    # records that as null (no return type), the same way a docs page never lists a return
    # type for a void method -- see crawl_notes.md-style note in the accompanying markdown.
    if ($null -eq $ReturnType) { return $null }
    if ($ReturnType.FullName -eq "System.Void") { return $null }
    return $ReturnType.ToString()
}

function Get-ParameterTypeString([System.Reflection.ParameterInfo] $Parameter) {
    $type = $Parameter.ParameterType
    if (-not $type.IsByRef) { return $type.ToString() }
    # A by-ref parameter's own ToString() gives the bare CLR form (e.g.
    # "Autodesk.Revit.DB.ModelCurveArray&"), which doesn't match how the docs parser records
    # an out/ref parameter: parse.py's _parse_member_signature splits "out ModelCurveArray
    # curveArray" into type="out ModelCurveArray", name="curveArray" -- i.e. it keeps the C#
    # "out"/"ref" keyword as a *prefix on the type string*, not a trailing "&". Confirmed on a
    # real Revit 2024 run that this mismatch made every real out/ref overload falsely report
    # SIGNATURE_MISMATCH. GetElementType() strips the by-ref marker to the real underlying
    # type; ParameterInfo.IsOut is metadata-only (readable under reflection-only loading) and
    # distinguishes "out" (IsOut true) from a plain "ref" (IsOut false) the same way the C#
    # compiler's own [Out] parameter attribute does -- Revit's API doesn't use C# 7's
    # readonly "in" parameters, so out/ref is the whole space to cover here.
    $keyword = if ($Parameter.IsOut) { "out" } else { "ref" }
    $elementType = $type.GetElementType()
    return "$keyword $($elementType.ToString())"
}

function Convert-ParametersToManifest($Parameters) {
    return @($Parameters | ForEach-Object {
        [ordered]@{ name = $_.Name; type = Get-ParameterTypeString $_ }
    })
}

function Convert-MembersToManifest([Type] $Type) {
    # DeclaredOnly: each type's own "members" list holds only members it directly declares.
    # Inherited members are reconstructed by Stage B (ground_truth._find_members) walking
    # inheritance_chain -- the same mechanism pipeline._build_known_edge_report already uses
    # for its nine hand-picked known-edge checks, generalized to every edge. This also keeps
    # the manifest's size from exploding across a deep hierarchy (Wall -> HostObject ->
    # Element -> ...), where flattening would repeat every ancestor member on every subclass.
    $flags = [System.Reflection.BindingFlags]::Public -bor `
        [System.Reflection.BindingFlags]::Instance -bor `
        [System.Reflection.BindingFlags]::Static -bor `
        [System.Reflection.BindingFlags]::DeclaredOnly

    $members = New-Object System.Collections.Generic.List[object]

    foreach ($prop in $Type.GetProperties($flags)) {
        # ReturnType/PropertyType/GetParameters() resolve their referenced types lazily --
        # if a property's type (or an indexer parameter's type) lives in an assembly that's
        # neither under -InstallDir nor loadable from the GAC, the resolve handler returns
        # $null and accessing that metadata throws (TypeLoadException/FileNotFoundException/
        # FileLoadException) instead of just returning an "unresolved" marker. Without this
        # guard, one such property anywhere in a multi-thousand-type scan aborts the entire
        # manifest instead of the single member -- confirmed as a real risk on the live
        # Revit 2024 run. Skip just this member (like an assembly that fails to load
        # entirely is recorded as unmatched rather than crashing the whole scan) and count
        # it for the run's summary line rather than staying silent about it.
        try {
            $accessor = $prop.GetGetMethod($true)
            if ($null -eq $accessor) { $accessor = $prop.GetSetMethod($true) }
            [void]$members.Add([ordered]@{
                name           = $prop.Name
                kind           = "property"
                declaring_type = $prop.DeclaringType.FullName
                return_type    = Get-ReturnTypeString $prop.PropertyType
                # @(...) here is load-bearing, not defensive style: PowerShell collapses a
                # function's 0- or 1-item return value to $null/a bare scalar when captured
                # across the call boundary (confirmed empirically -- a real 0- or 1-parameter
                # member serialized as "parameters": null / a bare object instead of an array
                # before this was added; see crawl_notes.md). Every call site below that
                # captures a collection-returning helper's result needs the same wrap.
                parameters     = @(Convert-ParametersToManifest $prop.GetIndexParameters())
                is_static      = if ($null -ne $accessor) { [bool]$accessor.IsStatic } else { $false }
            })
        } catch {
            $script:unresolvedMemberSkips++
            Write-Verbose "Skipping $($Type.FullName).$($prop.Name) (property): signature could not be resolved -- $($_.Exception.Message)"
        }
    }

    foreach ($method in $Type.GetMethods($flags)) {
        # IsSpecialName excludes property/event accessors (get_X/set_X/add_X/remove_X) and
        # operator overloads -- these aren't distinct "members" a docs page would list
        # separately from the property/event/operator itself.
        if ($method.IsSpecialName) { continue }
        # Same unresolved-signature guard as the property loop above.
        try {
            [void]$members.Add([ordered]@{
                name           = $method.Name
                kind           = "method"
                declaring_type = $method.DeclaringType.FullName
                return_type    = Get-ReturnTypeString $method.ReturnType
                parameters     = @(Convert-ParametersToManifest $method.GetParameters())
                is_static      = [bool]$method.IsStatic
            })
        } catch {
            $script:unresolvedMemberSkips++
            Write-Verbose "Skipping $($Type.FullName).$($method.Name) (method): signature could not be resolved -- $($_.Exception.Message)"
        }
    }

    return @($members.ToArray())
}

function Convert-EnumMembersToManifest([Type] $Type) {
    if (-not $Type.IsEnum) { return @() }
    # Enum.GetNames/GetValues need to construct real values and throw on a reflection-only
    # type ("The requested operation cannot be used on objects loaded by a
    # MetadataLoadContext.", confirmed empirically -- see crawl_notes.md). Reading the
    # type's own public static fields is metadata-only and works on both hosts: an enum's
    # named values are exactly its public static fields (confirmed against a real
    # reflection-only-loaded enum type in this project's dev sandbox).
    $flags = [System.Reflection.BindingFlags]::Public -bor [System.Reflection.BindingFlags]::Static
    return @($Type.GetFields($flags) | ForEach-Object { $_.Name })
}

function Convert-TypeToManifest([Type] $Type, [string] $AssemblyName) {
    return [ordered]@{
        full_type_name          = $Type.FullName
        assembly                = $AssemblyName
        kind                    = Get-TypeKindString $Type
        is_abstract             = [bool]$Type.IsAbstract
        base_type               = Get-BaseTypeName $Type
        # See the comment on the "parameters" assignment above -- @() wrapping at every
        # collection-returning-helper call site is load-bearing, confirmed by a real run
        # that serialized a single-ancestor inheritance_chain as a bare string instead of a
        # 1-element array before this was added.
        inheritance_chain       = @(Get-InheritanceChainNames $Type)
        implemented_interfaces  = @(Get-ImplementedInterfaceNames $Type)
        members                 = @(Convert-MembersToManifest $Type)
        enum_members            = @(Convert-EnumMembersToManifest $Type)
    }
}

function Test-NamespaceMatch([Type] $Type, [string] $Prefix) {
    return $Type.IsVisible -and $Type.Namespace -and $Type.Namespace.StartsWith($Prefix)
}

function Get-LoadableTypes([System.Reflection.Assembly] $Assembly, [string] $AssemblyLabel) {
    # A reflection-only-loaded assembly can still fail GetTypes() if some referenced type
    # can't be resolved (ReflectionOnlyAssemblyResolve/PathAssemblyResolver came up empty for
    # it) -- ReflectionTypeLoadException still carries every type that *did* load in its
    # .Types array (with nulls for the ones that didn't), so this is not treated as a hard
    # failure of the whole assembly. See docs/dll_reflection_v0.md's "external, not further
    # inspected" principle.
    #
    # Confirmed a real risk on a live Revit 2025 run: an assembly that matched fine in 2024
    # (RevitAPIIFC, DBManagedServices, RevitNET, RSCloudClient, ...) can come back with *zero*
    # types here in 2025 if a cross-assembly reference it needs was renamed/version-bumped in
    # the new install (e.g. AdskLicensingSDK_7 -> _8, the WCF-based ATFRevitWCFInterface
    # replaced by a gRPC-based ATFRevitGrpcInterface, ASM*229A -> *230A) -- every entry in
    # .Types comes back null, so the caller silently sees "matched: false", identical to an
    # assembly that never had any relevant types at all. Without logging *why* here, that's
    # indistinguishable from a normal non-match and the run's summary line stays silent about
    # what's actually a large, previously-working chunk of the manifest disappearing (see the
    # $script:typeLoadExceptionAssemblies warning below). LoaderExceptions carries the actual
    # missing/broken reference for each failed type, deduplicated for -Verbose.
    try {
        return $Assembly.GetTypes()
    } catch [System.Reflection.ReflectionTypeLoadException] {
        $loaded = @($_.Exception.Types | Where-Object { $null -ne $_ })
        $lostCount = $_.Exception.Types.Count - $loaded.Count
        if ($lostCount -gt 0) {
            $script:typeLoadExceptionAssemblies++
            $script:typeLoadExceptionTypesLost += $lostCount
            $distinctMessages = @($_.Exception.LoaderExceptions | Where-Object { $null -ne $_ } |
                ForEach-Object { $_.Message } | Select-Object -Unique -First 5)
            Write-Verbose "$AssemblyLabel : $lostCount type(s) failed to load out of $($_.Exception.Types.Count) (ReflectionTypeLoadException). Distinct loader exception(s):"
            foreach ($msg in $distinctMessages) { Write-Verbose "    $msg" }
        }
        return $loaded
    }
}


# -- Desktop (PowerShell 5.1 / .NET Framework) path ----------------------------

function Invoke-DesktopReflection {
    param([string[]] $DllPaths, [string] $Prefix, [string] $DotNetSharedFrameworkRoot)

    $byName = @{}
    foreach ($p in $DllPaths) {
        $name = [System.IO.Path]::GetFileNameWithoutExtension($p)
        if (-not $byName.ContainsKey($name)) { $byName[$name] = $p }
    }

    $dotNetSharedFrameworkIndex = Get-DotNetSharedFrameworkIndex $DotNetSharedFrameworkRoot

    # Cross-assembly references aren't auto-resolved by reflection-only loading -- redirect
    # any unresolved reference to the matching DLL already found under InstallDir, by simple
    # name. See docs/dll_reflection_v0.md, "Cross-assembly type references and
    # ReflectionOnlyAssemblyResolve".
    #
    # Confirmed on a real Windows + Revit 2024 run (see crawl_notes.md): a reference to a
    # plain .NET Framework BCL assembly (first hit was "System, Version=4.0.0.0, ...") isn't
    # under InstallDir at all -- it lives in the GAC. The resolve handler must fall back to
    # [Assembly]::ReflectionOnlyLoad($e.Name) (the assembly's own display name, not a path),
    # which uses the runtime's normal probing/GAC lookup, just in reflection-only mode -- this
    # is the standard fix for "Cannot resolve dependency to assembly '...' because it has not
    # been preloaded" against framework assemblies. Only fall back to $null (an unresolved,
    # external reference -- see docs/dll_reflection_v0.md's "external, not further inspected"
    # principle) if that also fails.
    #
    # The by-simple-name path lookup below can itself point at the *wrong* file: the script
    # deliberately indexes every *.dll under a Revit install (thousands of them, many
    # native/incompatible on purpose -- see "Finding the relevant assemblies" in
    # docs/dll_reflection_v0.md), so a colliding simple name (an unrelated or wrong-framework
    # DLL that happens to share a name with the real dependency, e.g. a vendored native
    # "System.dll"-named file elsewhere in the tree) can make $byName point at a file that
    # fails to load as the requested assembly even though the real one is perfectly
    # resolvable via the GAC. The path-based catch below must fall through to the GAC/normal
    # probing attempt instead of giving up immediately -- returning $null here before trying
    # ReflectionOnlyLoad($e.Name) would turn an otherwise-resolvable reference into an
    # unresolved one purely because of which file this scan happened to index first.
    $resolveHandler = [ResolveEventHandler] {
        param($sender, $e)
        $simpleName = ($e.Name -split ',')[0].Trim()
        if ($byName.ContainsKey($simpleName)) {
            try { return [System.Reflection.Assembly]::ReflectionOnlyLoadFrom($byName[$simpleName]) }
            catch { }  # fall through to GAC/normal-probing below rather than giving up here
        }
        # A requested identity like "System.Runtime, Version=8.0.0.0, ..." is never a
        # Framework/GAC assembly -- see Get-DotNetSharedFrameworkIndex's own comment.
        # ReflectionOnlyLoadFrom never executes a loaded assembly, only parses its metadata, so
        # a real modern .NET runtime's own file loads fine here even though this whole process
        # is old .NET Framework -- matching the *major* version (not the full patch version)
        # is what makes the returned assembly's identity actually satisfy the request.
        if ($e.Name -match 'Version=(\d+)\.') {
            $key = "$simpleName|$($Matches[1])"
            if ($dotNetSharedFrameworkIndex.ContainsKey($key)) {
                try { return [System.Reflection.Assembly]::ReflectionOnlyLoadFrom($dotNetSharedFrameworkIndex[$key]) }
                catch { }  # fall through to GAC/normal-probing below rather than giving up here
            }
        }
        try { return [System.Reflection.Assembly]::ReflectionOnlyLoad($e.Name) }
        catch { return $null }
    }
    [System.AppDomain]::CurrentDomain.add_ReflectionOnlyAssemblyResolve($resolveHandler)

    # Pre-seed the common .NET Framework assemblies most types reference (System, System.Core
    # for LINQ, System.Xml, System.Drawing for geometry-adjacent types, etc.) so the resolve
    # event above has less to do on-demand. Best-effort: any that fail to preload here will
    # still be attempted again via the resolve handler when actually referenced.
    foreach ($fx in @("mscorlib", "System", "System.Core", "System.Xml", "System.Drawing", "System.Windows.Forms")) {
        try { [System.Reflection.Assembly]::ReflectionOnlyLoad($fx) | Out-Null } catch { }
    }

    $assembliesScanned = New-Object System.Collections.Generic.List[object]
    $typeEntries = New-Object System.Collections.Generic.List[object]
    $loadFailures = 0

    foreach ($path in $DllPaths) {
        $name = [System.IO.Path]::GetFileNameWithoutExtension($path)
        try {
            $asm = [System.Reflection.Assembly]::ReflectionOnlyLoadFrom($path)
        } catch {
            # Expected for the large majority of DLLs under a Revit install (native interop,
            # third-party libraries, unrelated Autodesk components) -- not surfaced loudly.
            $loadFailures++
            [void]$assembliesScanned.Add([ordered]@{ path = $path; name = $name; matched = $false })
            continue
        }

        $types = @(Get-LoadableTypes $asm $name | Where-Object { Test-NamespaceMatch $_ $Prefix })
        $matched = $types.Count -gt 0
        [void]$assembliesScanned.Add([ordered]@{ path = $path; name = $name; matched = $matched })
        if ($matched) {
            foreach ($t in $types) {
                # Convert-TypeToManifest's own base_type/inheritance_chain/implemented_interfaces
                # guards handle the expected unresolved-ancestor/-interface case explicitly, but
                # this outer catch is the same "one bad thing shouldn't abort the whole scan"
                # safety net as the per-member guards -- skip just this one type, not the rest
                # of the assembly, if something still throws.
                try {
                    [void]$typeEntries.Add((Convert-TypeToManifest $t $name))
                } catch {
                    $script:unresolvedTypeSkips++
                    Write-Verbose "Skipping type $($t.FullName) entirely: $($_.Exception.Message)"
                }
            }
        }
    }

    Write-Verbose "Desktop reflection: $($DllPaths.Count - $loadFailures) loaded, $loadFailures failed to load (expected for most non-.NET/incompatible dlls)."
    return @{ AssembliesScanned = @($assembliesScanned.ToArray()); Types = @($typeEntries.ToArray()) }
}


# -- Core (PowerShell 7+ / .NET) path ------------------------------------------

function Invoke-CoreReflection {
    param([string[]] $DllPaths, [string] $Prefix, [string] $MlcAssemblyPath, [string] $ExtraRefDir)

    if (-not $MlcAssemblyPath) {
        $msg = "PowerShell 7+ ('Core' edition) detected, but -MetadataLoadContextAssembly was not " +
              "supplied. System.Reflection.MetadataLoadContext is a separate NuGet package, not " +
              "built in -- see docs/dll_reflection_v0.md and crawl_notes.md for how this was " +
              "confirmed and where to get it."
        throw $msg
    }
    Add-Type -Path $MlcAssemblyPath

    $runtimeDir = [System.Runtime.InteropServices.RuntimeEnvironment]::GetRuntimeDirectory()
    $runtimeDlls = @(Get-ChildItem -LiteralPath $runtimeDir -Filter *.dll -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty FullName)
    $extraDlls = @()
    if ($ExtraRefDir) {
        $extraDlls = @(Get-ChildItem -LiteralPath $ExtraRefDir -Filter *.dll -Recurse -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty FullName)
    } else {
        $warnMsg = "No -NetFrameworkReferenceAssembliesDir supplied. If the target dlls are " +
            "built for .NET Framework (as RevitAPI.dll is) while this host runs .NET/.NET Core, " +
            "MetadataLoadContext resolution will likely fail to find mscorlib/System.dll/etc -- " +
            "this combination has not been verified against real Revit dlls. See crawl_notes.md."
        Write-Warning $warnMsg
    }

    # Seed the resolver with every candidate assembly by simple name, preferring the install
    # dir's own copy over the host runtime's when both exist (matching the Desktop path's own
    # by-simple-name resolve strategy, applied here as an up-front resolver list instead of a
    # per-reference event, since MetadataLoadContext resolves eagerly through PathAssemblyResolver
    # rather than via a resolve event).
    $bySimpleName = @{}
    foreach ($p in (@($DllPaths) + @($extraDlls) + @($runtimeDlls))) {
        $name = [System.IO.Path]::GetFileNameWithoutExtension($p)
        if (-not $bySimpleName.ContainsKey($name)) { $bySimpleName[$name] = $p }
    }
    $coreAssemblyName = if ($ExtraRefDir) { "mscorlib" } else { "System.Private.CoreLib" }
    $resolver = New-Object System.Reflection.PathAssemblyResolver (, [string[]]($bySimpleName.Values))
    $mlc = New-Object System.Reflection.MetadataLoadContext($resolver, $coreAssemblyName)

    $assembliesScanned = New-Object System.Collections.Generic.List[object]
    $typeEntries = New-Object System.Collections.Generic.List[object]
    $loadFailures = 0

    foreach ($path in $DllPaths) {
        $name = [System.IO.Path]::GetFileNameWithoutExtension($path)
        try {
            $asm = $mlc.LoadFromAssemblyPath($path)
        } catch {
            $loadFailures++
            [void]$assembliesScanned.Add([ordered]@{ path = $path; name = $name; matched = $false })
            continue
        }

        $types = @(Get-LoadableTypes $asm $name | Where-Object { Test-NamespaceMatch $_ $Prefix })
        $matched = $types.Count -gt 0
        [void]$assembliesScanned.Add([ordered]@{ path = $path; name = $name; matched = $matched })
        if ($matched) {
            foreach ($t in $types) {
                # Convert-TypeToManifest's own base_type/inheritance_chain/implemented_interfaces
                # guards handle the expected unresolved-ancestor/-interface case explicitly, but
                # this outer catch is the same "one bad thing shouldn't abort the whole scan"
                # safety net as the per-member guards -- skip just this one type, not the rest
                # of the assembly, if something still throws.
                try {
                    [void]$typeEntries.Add((Convert-TypeToManifest $t $name))
                } catch {
                    $script:unresolvedTypeSkips++
                    Write-Verbose "Skipping type $($t.FullName) entirely: $($_.Exception.Message)"
                }
            }
        }
    }

    Write-Verbose "Core reflection: $($DllPaths.Count - $loadFailures) loaded, $loadFailures failed to load."
    return @{ AssembliesScanned = @($assembliesScanned.ToArray()); Types = @($typeEntries.ToArray()) }
}


# -- main -----------------------------------------------------------------------

# Incremented in Convert-MembersToManifest's per-member catch blocks, and in the outer
# per-type catch around Convert-TypeToManifest in both Invoke-*Reflection functions -- a
# script-scoped counter rather than a return value, since those are called deep inside the
# scan loop and threading a count back through every call site would be more invasive than
# these two shared counters.
$script:unresolvedMemberSkips = 0
$script:unresolvedTypeSkips = 0
# Incremented in Get-LoadableTypes: unlike the two counters above (which only ever drop a
# single already-enumerable member/type), these count whole types that never even made it
# into an assembly's $types list -- the failure mode that silently zeroed out RevitAPIIFC,
# DBManagedServices, RevitNET, RSCloudClient and others on a real Revit 2024 -> 2025 install
# upgrade (a cross-assembly dependency renamed/version-bumped between installs). Without this,
# such an assembly just reports "matched: false" with 0 types, indistinguishable from an
# assembly that was never relevant in the first place.
$script:typeLoadExceptionAssemblies = 0
$script:typeLoadExceptionTypesLost = 0

$dllPaths = @(Get-DllPaths $InstallDir)

$result = if ($isCore) {
    Invoke-CoreReflection -DllPaths $dllPaths -Prefix $NamespacePrefix `
        -MlcAssemblyPath $MetadataLoadContextAssembly -ExtraRefDir $NetFrameworkReferenceAssembliesDir
} else {
    Invoke-DesktopReflection -DllPaths $dllPaths -Prefix $NamespacePrefix -DotNetSharedFrameworkRoot $DotNetSharedFrameworkRoot
}

$manifest = [ordered]@{
    revit_version      = $RevitVersion
    generated_at        = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    namespace_prefix    = $NamespacePrefix
    assemblies_scanned  = $result.AssembliesScanned
    types               = $result.Types
}

# @() here guards against a nastier variant of the same collapse: when exactly one
# assembliesScanned entry matches, Where-Object's un-array-wrapped single result is that
# entry's own [ordered]@{...} hashtable -- and .Count on *that* silently returns its key
# count (3: path/name/matched), not "1 matching assembly". Confirmed empirically. See
# crawl_notes.md.
$matchedCount = @($result.AssembliesScanned | Where-Object { $_.matched }).Count
Write-Verbose "$matchedCount / $($result.AssembliesScanned.Count) scanned assemblies matched '$NamespacePrefix'; $($result.Types.Count) types collected."
if ($script:unresolvedMemberSkips -gt 0) {
    Write-Warning "$($script:unresolvedMemberSkips) member(s) skipped across the scan: their return/parameter types could not be resolved (neither under -InstallDir nor loadable from the GAC). Run with -Verbose to see which ones."
}
if ($script:unresolvedTypeSkips -gt 0) {
    Write-Warning "$($script:unresolvedTypeSkips) type(s) skipped entirely across the scan: their own metadata (beyond the base_type/inheritance_chain/implemented_interfaces fields, which record '<unresolved>' rather than being skipped) could not be converted. Run with -Verbose to see which ones."
}
if ($script:typeLoadExceptionAssemblies -gt 0) {
    Write-Warning ("$($script:typeLoadExceptionAssemblies) assembl(y/ies) hit ReflectionTypeLoadException while enumerating types " +
        "($($script:typeLoadExceptionTypesLost) type(s) failed to load and were dropped before this run ever saw them -- distinct " +
        "from the unresolved-member/-type counts above, which only apply to types that DID enumerate). This is the most likely " +
        "explanation if an assembly that matched in a previous version's manifest now shows 0 types / matched:false here: a " +
        "cross-assembly reference it needs was renamed, removed, or version-bumped in this install and can no longer be resolved " +
        "(neither under -InstallDir nor the GAC). Run with -Verbose to see each affected assembly's actual LoaderExceptions " +
        "messages, which name the specific missing/broken reference.")
}

$json = $manifest | ConvertTo-Json -Depth 12
# Set-Content/Out-File -Encoding utf8 always prepends a BOM on Windows PowerShell 5.1
# ("Desktop" edition) -- confirmed via Microsoft's own about_character_encoding docs -- which
# Stage B's ground_truth.load_manifest() (Python's json.loads) rejects outright ("Unexpected
# UTF-8 BOM"). UTF8Encoding($false) explicitly suppresses the BOM and behaves identically on
# both hosts (PS7/Core's Set-Content -Encoding utf8 is already BOM-less by default, so this
# doesn't change that side's behavior), so writing via File.WriteAllText with it sidesteps the
# Desktop-only BOM entirely rather than special-casing by host.
$utf8NoBom = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText($Out, $json, $utf8NoBom)
Write-Output "Wrote $Out ($($result.Types.Count) types from $matchedCount matched assemblies)"
