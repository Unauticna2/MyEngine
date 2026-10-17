param([string]$Exporter=(Join-Path $PSScriptRoot '../tools/powerpoint_export.ps1'))
# Execute the production export loop with COM-like objects. No Office required.
$ErrorActionPreference='Stop'
$tokens=$null;$errors=$null
$ast=[System.Management.Automation.Language.Parser]::ParseFile(
    [IO.Path]::GetFullPath($Exporter),[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
foreach ($node in $ast.FindAll({param($n)
    $n -is [System.Management.Automation.Language.FunctionDefinitionAst]
},$true)) { Invoke-Expression $node.Extent.Text }
$loop=$ast.Find({param($n)
    $n -is [System.Management.Automation.Language.ForEachStatementAst] -and
    $n.Body.Extent.Text.Contains('$stage="reading slide $index shape metadata"') -and
    $n.Variable.VariablePath.UserPath -eq 'shape'
},$true)
if (-not $loop) { throw 'Production shape export loop not found' }
$exportLoop=[scriptblock]::Create($loop.Extent.Text)
Add-Type @'
using System;
using System.IO;
public class RotationProbe {
    public double Angle;
    public bool Locked, FailExport, LockPosition;
    public int Writes, Exports, PositionWrites;
    public double ExportAngle;
    public double X, Y;
    public double Left { get {return X;} set {PositionWrites++; if(LockPosition) throw new ArgumentException("position locked"); X=value;} }
    public double Top { get {return Y;} set {PositionWrites++; if(LockPosition) throw new ArgumentException("position locked"); Y=value;} }
    public double Rotation {
        get {return Angle;}
        set {Writes++; if(Locked) throw new ArgumentException("rotation locked"); Angle=value;}
    }
    public void Export(string path, int kind, int width, int height, int mode) {
        Exports++; ExportAngle=Angle;
        if(FailExport) throw new IOException("export failed");
        File.WriteAllText(path,"mock PNG");
    }
}
'@
function Assert($condition,[string]$message) { if (-not $condition) { throw $message } }
function New-Probe([double]$angle,[bool]$locked) {
    $s=New-Object RotationProbe;$s.Angle=$angle;$s.Locked=$locked
    foreach ($pair in @{
        Id=9;Name='OLE group';Type=7;AlternativeText='';HasTextFrame=0;
        Width=100;Height=50;Visible=-1
    }.GetEnumerator()) { $s | Add-Member NoteProperty $pair.Key $pair.Value }
    return $s
}
function Run-Shape($inputShape) {
    $index=2;$items=@();$byShape=@{};$visible=@{'9'=-1}
    $originalShapes=@($inputShape)
    . $exportLoop
    return $items[0]
}
$cleanupWarnings=New-Object 'System.Collections.Generic.List[string]'
$sw=960;$sh=540
$Output=Join-Path ([IO.Path]::GetTempPath()) ('me-rotation-'+[guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($Output) | Out-Null
try {
    $s=New-Probe 0 $true
    $item=Run-Shape $s
    Assert ($s.Exports -eq 1 -and $s.Writes -eq 0) 'Locked zero-angle shape must export without any Rotation setter'
    Assert ($item.rotation -eq 0 -and $item.sourceShapeId -eq '9') 'Source shape metadata lost'
    Assert ($cleanupWarnings.Count -eq 0) 'No rotation restore is needed for unchanged shape'
    'PASS locked zero-angle shape, metadata and cleanup'

    $s=New-Probe 35 $false
    $item=Run-Shape $s
    Assert ($s.Exports -eq 1 -and $s.ExportAngle -eq 0 -and $s.Angle -eq 35 -and $s.Writes -eq 2) 'Rotated shape must export unrotated, then restore'
    Assert ($item.rotation -eq 35) 'Runtime rotation must remain the original angle'
    'PASS rotated shape and runtime angle'

    $s=New-Probe 35 $false;$s.FailExport=$true;$caught=$null
    try { Run-Shape $s | Out-Null } catch { $caught=$_ }
    Assert ($caught -and $caught.ToString().Contains('export failed')) 'Export errors must propagate'
    Assert ($s.Angle -eq 35 -and $s.Writes -eq 2) 'Restore changed rotation after export failure'
    'PASS failed export restores changed rotation'

    $s=New-Probe 35 $true;$caught=$null
    try { Run-Shape $s | Out-Null } catch { $caught=$_ }
    Assert ($caught -and $caught.ToString().Contains('rotation locked')) 'Real nonzero rotation failure must remain visible'
    Assert ($s.Exports -eq 0 -and $s.Writes -eq 1 -and $cleanupWarnings.Count -eq 0) 'Do not restore a rejected rotation or export at the wrong angle'
    'PASS genuine rotation error is preserved without extra cleanup errors'

    # Textless duplicate may be offset by PowerPoint. No move is needed because
    # text rectangles are relative to the copy, not absolute slide coordinates.
    $font=[pscustomobject]@{Color=[pscustomobject]@{RGB=255};Size=20;Name='Arial';Bold=0}
    $tr=[pscustomobject]@{Text='Dialogue';Font=$font;ParagraphFormat=[pscustomobject]@{Alignment=1}}
    $tr | Add-Member ScriptMethod Characters {param($start,$length) return $this}
    $frame=[pscustomobject]@{TextRange=$tr;MarginLeft=4;MarginRight=4;MarginTop=2;MarginBottom=2;AutoSize=0}
    $child=[pscustomobject]@{TextFrame=$frame;Left=60;Top=80;Width=100;Height=30}
    $children=[pscustomobject]@{Values=@($child);Count=1}
    $children | Add-Member ScriptMethod Item {param($i) return $this.Values[$i-1]}
    $copy=New-Probe 0 $true;$copy.X=56;$copy.Y=76;$copy.LockPosition=$true
    $copy | Add-Member NoteProperty GroupItems $children
    $range=[pscustomobject]@{Copy=$copy;Deleted=$false}
    $range | Add-Member ScriptMethod Item {param($i) return $this.Copy}
    $range | Add-Member ScriptMethod Delete {$this.Deleted=$true}
    $originalText=[pscustomobject]@{Type=1;Id=3;AlternativeText='';HasTextFrame=-1;Width=100;Height=30;TextFrame=[pscustomobject]@{HasText=-1;TextRange=[pscustomobject]@{Text='Dialogue'}}}
    $originalChildren=[pscustomobject]@{Values=@($originalText);Count=1}
    $originalChildren | Add-Member ScriptMethod Item {param($i) return $this.Values[$i-1]}
    $group=[pscustomobject]@{Type=6;GroupItems=$originalChildren;Range=$range}
    $group | Add-Member ScriptMethod Duplicate {return $this.Range}
    $slot=Export-TextSlot $group @(10,20,100,50) $Output 'textless.png'
    Assert ($copy.Writes -eq 0 -and $copy.PositionWrites -eq 0 -and $copy.Exports -eq 1) 'Do not rotate or move locked zero-angle textless copy'
    Assert (($slot.rect -join ',') -eq '8,6,92,26') 'Text slot must be relative to offset duplicate'
    Assert (($slot.style.color -join ',') -eq '1,0,0,1') 'Font color changed'
    Assert ($slot.sourceText -eq 'Dialogue' -and $tr.Text -eq '' -and $range.Deleted) 'Export clears and deletes only the duplicate'
    Assert ($originalText.TextFrame.TextRange.Text -eq 'Dialogue') 'Original text was changed'
    'PASS locked textless group with offset duplicate and original text preservation'

    $copy.FailExport=$true;$range.Deleted=$false;$tr.Text='Dialogue';$caught=$null
    try { Export-TextSlot $group @(10,20,100,50) $Output 'failed.png' | Out-Null } catch { $caught=$_ }
    Assert ($caught -and $caught.ToString().Contains('export failed') -and $range.Deleted) 'Delete textless duplicate even when export fails'
    'PASS textless copy cleanup on export failure'
} finally { Remove-Item -LiteralPath $Output -Recurse -Force }
'All rotation regression checks passed (mock COM; Windows PowerPoint not executed).'
