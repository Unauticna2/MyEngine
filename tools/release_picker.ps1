param([Parameter(Mandatory=$true)][string]$RequestPath,[Parameter(Mandatory=$true)][string]$ResultPath)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()
[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12
$request=Get-Content -LiteralPath $RequestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$form=New-Object Windows.Forms.Form
$form.Text='MyEngine — восстановление с GitHub'
$form.Size=New-Object Drawing.Size(760,610)
$form.StartPosition='CenterScreen'
$form.MinimumSize=$form.Size
$form.MaximizeBox=$false
function LabelAt([string]$text,[int]$y) {
    $label=New-Object Windows.Forms.Label
    $label.Text=$text;$label.SetBounds(18,$y,700,22);$form.Controls.Add($label)
}
function TextAt([string]$text,[int]$y) {
    $box=New-Object Windows.Forms.TextBox
    $box.Text=$text;$box.SetBounds(18,$y,700,25);$form.Controls.Add($box)
    return $box
}
LabelAt 'GitHub-репозиторий (автор/репозиторий; публичные релизы)' 16
$repo=TextAt ([string]$request.repository) 40
$load=New-Object Windows.Forms.Button
$load.Text='Получить список версий';$load.SetBounds(18,76,240,30);$form.Controls.Add($load)
$versions=New-Object Windows.Forms.ComboBox
$versions.DropDownStyle='DropDownList';$versions.SetBounds(18,116,700,28)
$form.Controls.Add($versions)
LabelAt 'Точный тег (можно указать старый тег вручную)' 154
$tag=TextAt ([string]$request.tag) 178
LabelAt 'Имя ZIP-файла в релизе' 216
$asset=TextAt ([string]$request.asset) 240
LabelAt 'Папка для восстановленных версий' 278
$folder=TextAt ([string]$request.destination) 302
$browse=New-Object Windows.Forms.Button
$browse.Text='Выбрать папку…';$browse.SetBounds(18,340,180,30);$form.Controls.Add($browse)
$remember=New-Object Windows.Forms.CheckBox
$remember.Text='Запомнить репозиторий и релиз для движка'
$remember.SetBounds(18,383,700,26);$remember.Visible= -not [bool]$request.isGame
$form.Controls.Add($remember)
$note=New-Object Windows.Forms.Label
$note.Text="Версия будет распакована в отдельную новую папку. Работающие файлы и сохранения останутся на месте. После загрузки откроется папка с восстановленной версией."
$note.SetBounds(18,420,700,55);$form.Controls.Add($note)
$status=New-Object Windows.Forms.Label
$status.SetBounds(18,481,700,28);$form.Controls.Add($status)
$go=New-Object Windows.Forms.Button
$go.Text='Восстановить';$go.SetBounds(460,520,150,32);$form.Controls.Add($go)
$cancel=New-Object Windows.Forms.Button
$cancel.Text='Отмена';$cancel.SetBounds(620,520,98,32);$form.Controls.Add($cancel)
$script:entries=@()
$load.Add_Click({
    try {
        if($repo.Text.Trim() -notmatch '^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}$'){throw 'Формат репозитория: автор/репозиторий'}
        $load.Enabled=$false;$status.Text='Получение последних 100 релизов…';$form.Refresh()
        $headers=@{'Accept'='application/vnd.github+json';'User-Agent'='MyEngine/2.5';'X-GitHub-Api-Version'='2022-11-28'}
        $releases=Invoke-RestMethod -Uri ('https://api.github.com/repos/'+$repo.Text.Trim()+'/releases?per_page=100') -Headers $headers -TimeoutSec 30
        $versions.Items.Clear();$script:entries=@()
        foreach($release in $releases){
            if($release.draft){continue}
            foreach($file in $release.assets){
                if($file.name.EndsWith('.zip') -and ((-not $request.assetPrefix) -or $file.name.StartsWith([string]$request.assetPrefix))){
                    $script:entries+=@{tag=[string]$release.tag_name;asset=[string]$file.name}
                    [void]$versions.Items.Add(([string]$release.tag_name)+' — '+([string]$file.name))
                }
            }
        }
        $status.Text='Найдено ZIP-сборок: '+$script:entries.Count
        if($script:entries.Count -gt 0){$versions.SelectedIndex=0}
    } catch { $status.Text='Не удалось получить список';[void][Windows.Forms.MessageBox]::Show($_.Exception.Message,'GitHub') }
    finally { $load.Enabled=$true }
})
$versions.Add_SelectedIndexChanged({
    $i=$versions.SelectedIndex
    if($i -ge 0){$tag.Text=$script:entries[$i].tag;$asset.Text=$script:entries[$i].asset}
})
$browse.Add_Click({
    $dialog=New-Object Windows.Forms.FolderBrowserDialog
    $dialog.Description='Папка для восстановленных версий'
    if(Test-Path -LiteralPath $folder.Text){$dialog.SelectedPath=$folder.Text}
    if($dialog.ShowDialog() -eq 'OK'){$folder.Text=$dialog.SelectedPath}
    $dialog.Dispose()
})
$go.Add_Click({
    if(-not $repo.Text.Trim() -or -not $tag.Text.Trim() -or -not $asset.Text.Trim() -or -not $folder.Text.Trim()){
        [void][Windows.Forms.MessageBox]::Show('Укажи репозиторий, тег, ZIP-файл и папку.','MyEngine');return
    }
    $result=@{repository=$repo.Text.Trim();tag=$tag.Text.Trim();asset=$asset.Text.Trim();destination=$folder.Text;remember=$remember.Checked}
    $json=$result | ConvertTo-Json
    [IO.File]::WriteAllText($ResultPath,$json,(New-Object Text.UTF8Encoding($false)))
    $form.Close()
})
$cancel.Add_Click({$form.Close()})
[void]$form.ShowDialog()
$form.Dispose()
