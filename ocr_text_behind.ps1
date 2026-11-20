[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null=[Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime]
$null=[Windows.Graphics.Imaging.SoftwareBitmap,Windows.Foundation,ContentType=WindowsRuntime]
$null=[Windows.Graphics.Imaging.BitmapPixelFormat,Windows.Foundation,ContentType=WindowsRuntime]
$null=[Windows.Graphics.Imaging.BitmapAlphaMode,Windows.Foundation,ContentType=WindowsRuntime]
$null=[Windows.Media.Ocr.OcrResult,Windows.Foundation,ContentType=WindowsRuntime]
$engine=[Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if(-not $engine){
 $lang=[Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages | Select-Object -First 1
 if($lang){$engine=[Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)}
}
$asTask=[System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {$_.Name -eq 'AsTask' -and $_.IsGenericMethodDefinition -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'} | Select-Object -First 1
function AwaitOcr($operation) {
 $task=$asTask.MakeGenericMethod([Windows.Media.Ocr.OcrResult]).Invoke($null,@($operation))
 return $task.GetAwaiter().GetResult()
}
while($null -ne ($line=[Console]::ReadLine())){
 $out=@{ok=$false;hits=@();backend='ocr'}
 try{
  if(-not $engine){throw 'ocr_unavailable'}
  $req=$line|ConvertFrom-Json
  $hits=New-Object 'System.Collections.Generic.HashSet[string]'
  foreach($region in $req.regions){
   if($hits.Contains([string]$region.id)){continue}
   $bitmap=$null
   try{
    $bytes=[Convert]::FromBase64String([string]$region.pixels)
    $buffer=[System.Runtime.InteropServices.WindowsRuntime.WindowsRuntimeBufferExtensions]::AsBuffer($bytes)
    $bitmap=[Windows.Graphics.Imaging.SoftwareBitmap]::CreateCopyFromBuffer($buffer,[Windows.Graphics.Imaging.BitmapPixelFormat]::Bgra8,[int]$region.width,[int]$region.height,[Windows.Graphics.Imaging.BitmapAlphaMode]::Ignore)
    $result=AwaitOcr ($engine.RecognizeAsync($bitmap))
    $roi=$region.roi
    foreach($ocrLine in $result.Lines){
     foreach($word in $ocrLine.Words){
      $r=$word.BoundingRect
      if($word.Text -match '\S' -and ($r.X+$r.Width/2) -ge $roi[0] -and ($r.X+$r.Width/2) -lt $roi[2] -and ($r.Y+$r.Height/2) -ge $roi[1] -and ($r.Y+$r.Height/2) -lt $roi[3]){
       $null=$hits.Add([string]$region.id);break
      }
     }
     if($hits.Contains([string]$region.id)){break}
    }
   }finally{if($bitmap){$bitmap.Dispose()}}
  }
  $out.ok=$true;$out.hits=@($hits|ForEach-Object {$_})
 }catch{$out.why='ocr_failed'}
 [Console]::Out.WriteLine(($out|ConvertTo-Json -Compress -Depth 4));[Console]::Out.Flush()
}
