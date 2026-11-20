# Claude 앱 Code 입력창 옆 '사용량' 버튼의 작은 창을 잠깐 열어 최신 사용량을 읽고 바로 닫는다.
# 출력: JSON 한 줄 {ok, s_pct, s_reset, w_pct, w_reset, why}. pet.pyw 가 '동기화' 때 실행한다.
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$A  = [System.Windows.Automation.AutomationElement]
$TS = [System.Windows.Automation.TreeScope]
$CT = [System.Windows.Automation.ControlType]
function NameIs($n) { New-Object System.Windows.Automation.PropertyCondition($A::NameProperty, $n) }
function TypeIs($t) { New-Object System.Windows.Automation.PropertyCondition($A::ControlTypeProperty, $t) }
function Win { $A::RootElement.FindFirst($TS::Children, (NameIs "Claude")) }
$o = @{ ok = $false; s_pct = $null; s_reset = ""; w_pct = $null; w_reset = ""; why = "" }
$ec = $null
try {
    $w = Win
    if (-not $w) { throw "no Claude window" }
    $btn = $null
    foreach ($b in $w.FindAll($TS::Descendants, (TypeIs $CT::Button))) {
        if ($b.Current.Name -like 'Usage:*') { $btn = $b; break }
    }
    if (-not $btn) { throw "no usage button" }
    $ec = $btn.GetCurrentPattern([System.Windows.Automation.ExpandCollapsePattern]::Pattern)
    if ($ec.Current.ExpandCollapseState -ne 'Expanded') { $ec.Expand() }
    $popC = New-Object System.Windows.Automation.AndCondition((NameIs "Usage"), (TypeIs $CT::Window))
    $pop = $null
    for ($i = 0; $i -lt 15; $i++) {
        Start-Sleep -Milliseconds 100
        $pop = (Win).FindFirst($TS::Descendants, $popC)
        if ($pop -and $pop.FindFirst($TS::Descendants, (TypeIs $CT::ProgressBar))) { break }
    }
    if (-not $pop) { throw "usage popup did not open" }
    Start-Sleep -Milliseconds 150   # 숫자가 서버에서 새로 들어올 시간
    # 화면 순서: 라벨, 'Resets ...', 진행 막대(이름 = 라벨, 값 = %)
    $label = ""
    $orC = New-Object System.Windows.Automation.OrCondition((TypeIs $CT::Text), (TypeIs $CT::ProgressBar))
    foreach ($x in $pop.FindAll($TS::Descendants, $orC)) {
        $n = $x.Current.Name
        $k = if ($n -match 'hour|session') { "s" } elseif ($n -match '^Weekly.*all models|^All models') { "w" } else { "" }
        if ($x.Current.ControlType -eq $CT::ProgressBar) {
            if ($k) {
                try { $o["$($k)_pct"] = $x.GetCurrentPattern([System.Windows.Automation.RangeValuePattern]::Pattern).Current.Value } catch {}
            }
        } elseif ($k) { $label = $k }
        elseif ($n -like 'Resets*' -and $label) { if (-not $o["$($label)_reset"]) { $o["$($label)_reset"] = $n } }
    }
    $o.ok = ($o.s_pct -ne $null) -or ($o.w_pct -ne $null)
    if (-not $o.ok) { $o.why = "no values in popup" }
} catch {
    $o.why = $_.Exception.Message
} finally {
    if ($ec) { try { $ec.Collapse() } catch {} }
}
[Console]::Out.WriteLine(($o | ConvertTo-Json -Compress))
