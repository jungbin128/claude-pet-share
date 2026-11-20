# Claude 데스크톱 창의 '채팅(Claude) / Code' 모드 전환 버튼과 응답 중 표시를 읽어
# 1.5초마다 JSON 한 줄로 출력한다. pet.pyw 가 실행하고 읽는다. 펫이 꺼지면 같이 끝난다.
param([int]$ParentPid)
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$A  = [System.Windows.Automation.AutomationElement]
$TS = [System.Windows.Automation.TreeScope]
$CT = [System.Windows.Automation.ControlType]
function NameCond($n) { New-Object System.Windows.Automation.PropertyCondition($A::NameProperty, $n) }
function TypeCond($t) { New-Object System.Windows.Automation.PropertyCondition($A::ControlTypeProperty, $t) }
$modeC  = New-Object System.Windows.Automation.AndCondition((NameCond "Mode"), (TypeCond $CT::Group))
$radioC = TypeCond $CT::RadioButton
$respC  = NameCond "Claude is responding"
$docC   = TypeCond $CT::Document
$winC   = NameCond "Claude"
$btnC   = TypeCond $CT::Button
$walker = [System.Windows.Automation.TreeWalker]::ControlViewWalker
$tick   = 0

# 설정 > 사용량 탭: 글자를 화면 순서대로 읽어 'Current session' / 'All models' 바로 뒤의 'Resets ...' 를 짝짓는다
function UsageResets($w) {
    $r = @{ s = ""; w = "" }
    $e = $w.FindFirst($TS::Descendants, (NameCond "Current session"))
    if (-not $e) { return $r }
    $p = $e
    for ($i = 0; $i -lt 8; $i++) {           # 'Weekly limits' 까지 담는 상자까지 올라간다
        $q = $walker.GetParent($p)
        if (-not $q) { break }
        $p = $q
        if ($p.FindFirst($TS::Descendants, (NameCond "All models"))) { break }
    }
    $label = ""
    foreach ($x in $p.FindAll($TS::Descendants, (TypeCond $CT::Text))) {
        $n = $x.Current.Name
        if ($n -eq "Current session") { $label = "s" }
        elseif ($n -eq "All models" -or $n -like "Weekly*") { $label = "w" }
        elseif ($n -like "Resets*" -and $label) { if (-not $r[$label]) { $r[$label] = $n }; $label = "" }
    }
    return $r
}

while ($true) {
    if ($ParentPid -and -not (Get-Process -Id $ParentPid -ErrorAction SilentlyContinue)) { break }
    $o = @{ ok = $false; chat = ""; code = ""; active = ""; responding = $false; doc = ""; ubtn = ""; sreset = ""; wreset = "" }
    $tick++
    try {
        $w = $A::RootElement.FindFirst($TS::Children, $winC)
        if ($w) {
            $o.ok = $true
            $mode = $w.FindFirst($TS::Descendants, $modeC)
            if ($mode) {
                foreach ($r in $mode.FindAll($TS::Descendants, $radioC)) {
                    $n = $r.Current.Name
                    $sel = $false
                    try { $sel = $r.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Current.IsSelected } catch {}
                    if ($n -like 'Code*') { $o.code = ($n -replace '^Code,?\s*', ''); if ($sel) { $o.active = 'code' } }
                    else { $o.chat = ($n -replace '^Claude,?\s*', ''); if ($sel) { $o.active = 'chat' } }
                }
            }
            # 사용량: Code 입력창 옆 버튼(가장 급한 한도 하나) + 설정 사용량 탭이 열려 있으면 두 리셋 모두
            if ($tick % 2 -eq 0) {
                foreach ($b in $w.FindAll($TS::Descendants, $btnC)) {
                    if ($b.Current.Name -like 'Usage:*') { $o.ubtn = $b.Current.Name; break }
                }
                $ur = UsageResets $w
                $o.sreset = $ur.s; $o.wreset = $ur.w
            }
            if ($o.active -eq 'chat') {
                $o.responding = [bool]($w.FindFirst($TS::Descendants, $respC))
                $d = $w.FindFirst($TS::Descendants, $docC)
                if ($d) { $o.doc = $d.Current.Name }
            }
        }
    } catch { $o.err = $_.Exception.Message }
    try { [Console]::Out.WriteLine(($o | ConvertTo-Json -Compress)); [Console]::Out.Flush() } catch { break }
    Start-Sleep -Milliseconds 1500
}
