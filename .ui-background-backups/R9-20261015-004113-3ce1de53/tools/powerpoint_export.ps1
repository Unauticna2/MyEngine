param([string]$Source='', [Parameter(Mandatory=$true)][string]$Output)
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=New-Object Text.UTF8Encoding($false)
if ($Source) {
    if ([IO.Path]::GetExtension($Source).ToLower() -ne '.pptx') { throw 'Use .pptx.' }
    $Source=[IO.Path]::GetFullPath($Source)
}
$Output=[IO.Path]::GetFullPath($Output)
[IO.Directory]::CreateDirectory($Output) | Out-Null
$app=$null;$original=$null;$deck=$null;$failure=$null;$stage='starting exporter'
$copyFolder=$null;$copyPath=$null;$ownsDeck=$false;$openedCopy=$false;$closedCopy=$false
$mutex=$null;$hasMutex=$false
$cleanupWarnings=New-Object 'System.Collections.Generic.List[string]'
function Format-ExportError($record) {
    $parts=New-Object 'System.Collections.Generic.List[string]'
    $exception=$record.Exception
    while ($null -ne $exception) {
        $parts.Add(('{0} (0x{1:X8}): {2}' -f $exception.GetType().FullName,$exception.HResult,$exception.Message))
        $exception=$exception.InnerException
    }
    if ($record.InvocationInfo.PositionMessage) { $parts.Add($record.InvocationInfo.PositionMessage) }
    return ($parts -join [Environment]::NewLine)
}
function Try-Cleanup([string]$name,[scriptblock]$action) {
    # Cleanup never hides the original error and never quits the user's app.
    try { & $action | Out-Null }
    catch { $cleanupWarnings.Add($name+': '+(Format-ExportError $_)) }
}
function Normalize-JsonQuotes([string]$text) {
    $builder=New-Object Text.StringBuilder
    $closing=@();$escaped=$false
    foreach ($ch in $text.ToCharArray()) {
        $code=[int]$ch
        if ($closing.Count -eq 0) {
            if ($code -eq 34) { $closing=@(34);[void]$builder.Append($ch) }
            elseif ($code -eq 8220) { $closing=@(8221);[void]$builder.Append([char]34) }
            elseif ($code -eq 8222) { $closing=@(8220,8221);[void]$builder.Append([char]34) }
            elseif ($code -eq 171) { $closing=@(187);[void]$builder.Append([char]34) }
            elseif ($code -eq 160 -or $code -eq 8239) { [void]$builder.Append(' ') }
            else { [void]$builder.Append($ch) }
        } elseif ($escaped) { [void]$builder.Append($ch);$escaped=$false }
        elseif ($code -eq 92) { [void]$builder.Append($ch);$escaped=$true }
        elseif ($closing -contains $code) { [void]$builder.Append([char]34);$closing=@() }
        else { [void]$builder.Append($ch) }
    }
    return $builder.ToString()
}
function Read-Metadata($shape) {
    $text=Normalize-JsonQuotes ([string]$shape.AlternativeText)
    if ($text.Trim().StartsWith('{')) {
        try { $m=ConvertFrom-Json $text; if ($m.myengine) { $m=$m.myengine }; return @{Metadata=$m;Inline=$false} }
        catch { throw "Invalid JSON in Alt Text of shape '$($shape.Name)': $($_.Exception.Message)" }
    }
    # Also accept a whole shape containing {"myengine": {...}}. Ordinary
    # captions (including ordinary JSON) remain visible. Alt Text wins.
    if ($shape.HasTextFrame -ne 0 -and $shape.TextFrame.HasText -ne 0) {
        $text=Normalize-JsonQuotes (([string]$shape.TextFrame.TextRange.Text).Trim())
        if ($text.StartsWith('{') -and $text -cmatch '"myengine"\s*:') {
            try {
                $m=ConvertFrom-Json $text
                if ($m.myengine -isnot [System.Management.Automation.PSCustomObject]) { throw 'myengine must be a JSON object' }
                return @{Metadata=$m.myengine;Inline=$true}
            } catch { throw "Invalid MyEngine JSON in text of shape '$($shape.Name)': $($_.Exception.Message)" }
        }
    }
    return $null
}
try {
    $stage='acquiring import lock'
    $mutex=New-Object Threading.Mutex($false,'Local\MyEngine2.PowerPointExport')
    try { $hasMutex=$mutex.WaitOne(0) }
    catch [Threading.AbandonedMutexException] { $hasMutex=$true }
    if (-not $hasMutex) { throw 'Another MyEngine PowerPoint import is still running.' }
    $stage='connecting to the running PowerPoint.Application'
    $app=[Runtime.InteropServices.Marshal]::GetActiveObject('PowerPoint.Application')
    $stage='selecting the open presentation'
    if ($Source) {
        foreach ($candidate in $app.Presentations) {
            if ([string]::Equals([string]$candidate.FullName,$Source,[StringComparison]::OrdinalIgnoreCase)) {
                $original=$candidate;break
            }
        }
        if ($null -eq $original) { throw "Open this file in PowerPoint first: $Source" }
    } else {
        if ($app.Presentations.Count -eq 0) { throw 'Open a .pptx presentation in PowerPoint first.' }
        $original=$app.ActivePresentation
    }
    if ($null -eq $original) { throw 'Select the presentation window in PowerPoint, then switch to the editor.' }
    $originalName=[string]$original.Name
    $originalDirectory=[string]$original.Path
    if ([IO.Path]::GetExtension($originalName).ToLower() -ne '.pptx' -or -not $originalDirectory) {
        throw 'Save the presentation as .pptx once, leave it open, then import again.'
    }
    if (-not [IO.Directory]::Exists($originalDirectory)) {
        throw 'Use a local .pptx file. Save a local copy of the online presentation and open it.'
    }
    $stage='creating a snapshot of the open presentation (SaveCopyAs)'
    $token=[Guid]::NewGuid().ToString('N')
    $copyFolder=Join-Path ([IO.Path]::GetTempPath()) ('MyEngine2-PowerPoint-'+$token)
    [IO.Directory]::CreateDirectory($copyFolder) | Out-Null
    $copyPath=Join-Path $copyFolder ('MyEngine2-Export-'+$token+'.pptx')
    # Includes unsaved edits. Never call Save, Close or set Saved on $original.
    $original.SaveCopyAs($copyPath,24,0)
    [IO.File]::Copy($copyPath,(Join-Path $Output "_powerpoint_snapshot.pptx"))
    $stage='checking snapshot format'
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $zip=[IO.Compression.ZipFile]::OpenRead($copyPath)
    try {
        foreach ($entry in $zip.Entries) {
            if ($entry.FullName.ToLower().EndsWith('vbaproject.bin')) { throw 'Macro-enabled presentations are not imported.' }
        }
    } finally { $zip.Dispose() }
    $stage='opening the temporary snapshot'
    $openedCopy=$true
    $deck=$app.Presentations.Open($copyPath,0,0,0)
    # Only close a presentation whose exact path belongs to this export.
    $ownsDeck=[string]::Equals([string]$deck.FullName,$copyPath,[StringComparison]::OrdinalIgnoreCase)
    if (-not $ownsDeck) { throw 'PowerPoint did not return the temporary snapshot. Export stopped.' }
    $stage='reading slide size'
    $sw=[double]$deck.PageSetup.SlideWidth;$sh=[double]$deck.PageSetup.SlideHeight
    if ($deck.Slides.Count -gt 256) { throw 'UI limit: 256 slides.' }
    $slides=@();$warnings=@()
    foreach ($slide in $deck.Slides) {
        $index=[int]$slide.SlideIndex;$items=@();$byShape=@{};$animations=@();$slideMeta=$null
        $stage="reading slide $index shapes"
        # Exporting inline metadata uses short-lived duplicates. Enumerate a
        # snapshot so changing the COM Shapes collection cannot skip a shape.
        $originalShapes=@($slide.Shapes)
        if ($originalShapes.Count -gt 2048) { throw "Slide ${index}: UI limit is 2048 elements." }
        $visible=@{}
        # Export only individual shapes. The slide background would cover the
        # game scene, so no full-slide image or background field is generated.
        foreach ($shape in $originalShapes) { $visible[[string]$shape.Id]=$shape.Visible }
        foreach ($shape in $originalShapes) {
            $stage="reading slide $index shape metadata"
            $info=Read-Metadata $shape
            $meta=$null;if ($info) { $meta=$info.Metadata }
            if ($meta -and $meta.slide) { $slideMeta=$meta.slide;continue }
            if ([int]$shape.Type -eq 16) { $warnings+="Slide ${index}: media '$($shape.Name)' is exported as a static poster" }
            $id=[string]$shape.Id;$filename="slide_${index}_shape_${id}.png"
            $stage="exporting slide $index shape $id"
            $angle=[double]$shape.Rotation
            $rect=@([double]$shape.Left,[double]$shape.Top,[Math]::Max(1,[double]$shape.Width),[Math]::Max(1,[double]$shape.Height))
            $exportShape=$shape;$duplicate=$null
            try {
                if ($info -and $info.Inline) {
                    # Export a temporary copy without its JSON caption. This
                    # keeps the original text formatting and animations intact.
                    $duplicate=$shape.Duplicate();$exportShape=$duplicate.Item(1)
                    $exportShape.TextFrame.AutoSize=0
                    $exportShape.TextFrame.TextRange.Text=''
                    $exportShape.LockAspectRatio=0
                    $exportShape.Width=$rect[2];$exportShape.Height=$rect[3]
                    $exportShape.Left=$rect[0];$exportShape.Top=$rect[1]
                }
                $exportShape.Visible=-1
                $exportShape.Rotation=0
                $exportShape.Export((Join-Path $Output $filename),2,[int]($sw*2),[int]($sh*2),1)
            } finally {
                if ($duplicate) { Try-Cleanup "slide $index shape $id duplicate.Delete" { $duplicate.Delete() } }
                else { Try-Cleanup "slide $index shape $id restore Rotation" { $shape.Rotation=$angle } }
            }
            $item=[ordered]@{id=$id;sourceShapeId=$id;name=[string]$shape.Name;image=$filename;rect=$rect;rotation=$angle;enabled=($visible[$id] -ne 0);onClick=@();animations=@()}
            if ($meta) {
                foreach ($property in $meta.PSObject.Properties) {
                    if (@('id','enabled','onClick','animations','frames','fps','color','opacity','animationMode','waitForAnimation') -contains $property.Name) { $item[$property.Name]=$property.Value }
                }
            }
            $byShape[$id]=[string]$item.id;$items+=,$item
        }
        $stage="reading slide $index animations"
        $sequenceList=@(@{sequence=$slide.TimeLine.MainSequence;id='main'})
        for ($seqIndex=1;$seqIndex -le $slide.TimeLine.InteractiveSequences.Count;$seqIndex++) {
            $sequenceList+=,@{sequence=$slide.TimeLine.InteractiveSequences.Item($seqIndex);id="interactive_$seqIndex"}
        }
        foreach ($sequenceInfo in $sequenceList) {
        $group=0;$lastStart=0.0;$lastEnd=0.0;$triggerId=$null;$triggerGroup=$null
        foreach ($effect in $sequenceInfo.sequence) {
            $shapeId=[string]$effect.Shape.Id
            if (-not $byShape.ContainsKey($shapeId)) { continue }
            $kind=switch ([int]$effect.EffectType) { 1 {'appear'} 10 {'fade'} 23 {'zoom'} 2 {'fly'} 61 {'spin'} default {''} }
            if (-not $kind) { $warnings+="Slide ${index}: effect $($effect.EffectType) on $shapeId is not supported";continue }
            $trigger=[int]$effect.Timing.TriggerType;$delay=[double]$effect.Timing.TriggerDelayTime;$duration=[double]$effect.Timing.Duration
            if ($trigger -eq 4) {
                $triggerShapeId=[string]$effect.Timing.TriggerShape.Id
                if (-not $byShape.ContainsKey($triggerShapeId)) { $warnings+="Slide ${index}: animation trigger shape $triggerShapeId was not imported";continue }
                $group++;$triggerId=$byShape[$triggerShapeId];$triggerGroup=$sequenceInfo.id+"_$group";$start=$delay
            }
            elseif ($trigger -eq 1) { $group++;$start=$delay }
            elseif ($trigger -eq 2) { $start=$lastStart+$delay }
            elseif ($trigger -eq 3) { $start=$lastEnd+$delay }
            elseif ($trigger -eq 0) { $start=$delay }
            else { $warnings+="Slide ${index}: interactive animation trigger $trigger is not supported";continue }
            $animation=[ordered]@{element=$byShape[$shapeId];kind=$kind;group=$group;delay=$start;duration=$duration;exit=([int]$effect.Exit -ne 0)}
            if ($triggerId) { $animation.triggerElement=$triggerId;$animation.triggerGroup=$triggerGroup }
            if ($kind -eq 'fly') {
                # Default below-to-position; the imported direction is retained for JSON editing.
                $animation.offset=@(0,$sh);$animation.powerPointDirection=[int]$effect.EffectParameters.Direction
                $warnings+="Slide ${index}: Fly uses a default offset; review direction on element $shapeId"
            }
            if ($kind -eq 'spin') { $animation.degrees=360;$warnings+="Slide ${index}: Spin uses 360 degrees; review amount on element $shapeId" }
            $animations+=,$animation;$lastStart=$start;$lastEnd=$start+$duration
        }
        }
        $entry=[ordered]@{id=[string]$index;sourceSlideId=[string]$slide.SlideID;name=[string]$slide.Name;enabled=([int]$slide.SlideShowTransition.Hidden -eq 0);elements=$items;animations=$animations;onEnter=@()}
        if ($slideMeta) { foreach ($property in $slideMeta.PSObject.Properties) { if (@('id','enabled','onEnter','modal','transition','advanceAfter','advanceOnClick') -contains $property.Name) { $entry[$property.Name]=$property.Value } } }
        $slides+=,$entry
    }
    $stage='writing interface.ui.json'
    $result=[ordered]@{format=1;kind='MyEngine.UI';width=$sw;height=$sh;sourcePresentation=$originalName;startSlide=$(if($slides.Count){$slides[0].id}else{''});slides=$slides;warnings=$warnings}
    $info=ConvertTo-Json -InputObject @{directory=$originalDirectory;source=[string]$original.FullName}
    [IO.File]::WriteAllText((Join-Path $Output '_powerpoint_source.json'),$info,(New-Object Text.UTF8Encoding($false)))
    $json=ConvertTo-Json -InputObject $result -Depth 40
    [IO.File]::WriteAllText((Join-Path $Output 'interface.ui.json'),$json,(New-Object Text.UTF8Encoding($false)))
    Write-Output "Exported $($slides.Count) slides."
} catch {
    $failure=$_
    [Console]::Error.WriteLine("PowerPoint export failed at stage '$stage':")
    [Console]::Error.WriteLine((Format-ExportError $failure))
} finally {
    if ($null -ne $deck -and $ownsDeck) {
        Try-Cleanup 'snapshot.Saved' { $deck.Saved=-1 }
        try { $deck.Close();$closedCopy=$true }
        catch { $cleanupWarnings.Add('snapshot.Close: '+(Format-ExportError $_)) }
        Try-Cleanup 'release presentation' { [Runtime.InteropServices.Marshal]::FinalReleaseComObject($deck) }
    }
    if ($null -ne $original) {
        Try-Cleanup 'release original reference' { [Runtime.InteropServices.Marshal]::ReleaseComObject($original) }
    }
    if ($null -ne $app) {
        Try-Cleanup 'release PowerPoint reference' { [Runtime.InteropServices.Marshal]::ReleaseComObject($app) }
    }
    if ($copyFolder) {
        if (-not $openedCopy -or $closedCopy) {
            Try-Cleanup 'delete snapshot' {
                if ([IO.File]::Exists($copyPath)) { [IO.File]::Delete($copyPath) }
                if ([IO.Directory]::Exists($copyFolder)) { [IO.Directory]::Delete($copyFolder) }
            }
        } else {
            $cleanupWarnings.Add('A temporary snapshot may still be open. Close it without saving: '+$copyPath)
        }
    }
    if ($hasMutex) { Try-Cleanup 'release import lock' { $mutex.ReleaseMutex() } }
    if ($null -ne $mutex) { Try-Cleanup 'dispose import lock' { $mutex.Dispose() } }
}
foreach ($warning in $cleanupWarnings) { [Console]::Error.WriteLine('Cleanup warning: '+$warning) }
if ($null -ne $failure) { exit 1 }
exit 0
