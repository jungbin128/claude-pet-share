# Claude 데스크톱 앱을 접근성(UI Automation)으로 조작한다. pet.pyw 가 호출.
#   -Action open : 해당 모드(code/chat)로 바꾸고 사이드바에서 -Title 대화를 연다
#   -Action send : open 후 입력창(Prompt)에 -TextFile 내용을 붙여넣고 Enter
#   -Action new  : 해당 모드에서 새 대화를 시작하고 입력창에 커서를 둔다
#   -Action usage: 왼쪽 아래 프로필 메뉴 > Settings > Usage 탭을 연다 (펫이 리셋 시각을 읽어 기억하도록)
# 펫이 먼저 Claude 창을 앞으로 가져온 뒤 실행된다.
param([string]$Action = "open", [string]$Mode = "code", [string]$Title = "", [string]$TextFile = "")
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes, System.Windows.Forms
$A  = [System.Windows.Automation.AutomationElement]
$TS = [System.Windows.Automation.TreeScope]
$CT = [System.Windows.Automation.ControlType]
function NameIs($n) { New-Object System.Windows.Automation.PropertyCondition($A::NameProperty, $n) }
function TypeIs($t) { New-Object System.Windows.Automation.PropertyCondition($A::ControlTypeProperty, $t) }
function Both($c1, $c2) { New-Object System.Windows.Automation.AndCondition($c1, $c2) }
function Log($m) { Add-Content -Path (Join-Path $PSScriptRoot "claude_ui.log") -Value ("{0} {1}" -f (Get-Date -Format "HH:mm:ss"), $m) -Encoding UTF8 }
function Win { return $A::RootElement.FindFirst($TS::Children, (NameIs "Claude")) }
function Press($el) {
    try { $el.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke(); return } catch {}
    try { $el.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Select(); return } catch {}
    $el.SetFocus(); [System.Windows.Forms.SendKeys]::SendWait(" ")
}

try {
    $w = Win
    if (-not $w) { throw "no Claude window" }
    if ($Action -eq "usage") {
        $usageBtn = Both (NameIs "Usage") (TypeIs $CT::Button)
        $u = $w.FindFirst($TS::Descendants, $usageBtn)   # 설정 창이 이미 열려 있으면 탭만 누른다
        if (-not $u) {
            $wr = $w.Current.BoundingRectangle
            $prof = $null
            foreach ($b in $w.FindAll($TS::Descendants, (TypeIs $CT::Button))) {
                $r = $b.Current.BoundingRectangle
                if ($r.X -lt $wr.X + 60 -and $r.Y -gt $wr.Bottom - 60) { $prof = $b; break }
            }
            if (-not $prof) { throw "profile button not found" }
            try { $prof.GetCurrentPattern([System.Windows.Automation.ExpandCollapsePattern]::Pattern).Expand() } catch { Press $prof }
            Start-Sleep -Milliseconds 700
            $mi = (Win).FindFirst($TS::Descendants, (Both (NameIs "Settings") (TypeIs $CT::MenuItem)))
            if (-not $mi) { throw "Settings menu item not found" }
            Press $mi
            for ($i = 0; $i -lt 10 -and -not $u; $i++) {
                Start-Sleep -Milliseconds 250
                $u = (Win).FindFirst($TS::Descendants, $usageBtn)
            }
        }
        if (-not $u) { throw "Usage tab not found" }
        Press $u
        Log "ok usage"
        return
    }
    # 1) 모드 전환 (Claude=채팅·코워크 / Code)
    $modeGroup = $w.FindFirst($TS::Descendants, (Both (NameIs "Mode") (TypeIs $CT::Group)))
    if ($modeGroup) {
        foreach ($r in $modeGroup.FindAll($TS::Descendants, (TypeIs $CT::RadioButton))) {
            $isCode = $r.Current.Name -like "Code*"
            if (($Mode -eq "code") -eq $isCode) {
                $sel = $false
                try { $sel = $r.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Current.IsSelected } catch {}
                if (-not $sel) { Press $r; Start-Sleep -Milliseconds 800; $w = Win }
            }
        }
    }
    # 2) 대화 열기 또는 새 대화
    $buttons = $w.FindAll($TS::Descendants, (TypeIs $CT::Button))
    if ($Action -eq "new") {
        $btn = $null
        foreach ($b in $buttons) { if ($b.Current.Name -in @("New", "New chat", "New session", "New task")) { $btn = $b; break } }
        if ($btn) { Press $btn; Start-Sleep -Milliseconds 700 } else { Log "new button not found" }
    } elseif ($Title) {
        $hit = $null
        foreach ($b in $buttons) {
            $n = $b.Current.Name
            if ($n -eq $Title -or $n.StartsWith($Title + " ")) { $hit = $b; break }
        }
        if ($hit) { Press $hit; Start-Sleep -Milliseconds 700 } else { Log "session not found: $Title" }
    }
    # 3) 입력창에 커서 두기 / 메시지 보내기
    $w = Win
    $prompt = $w.FindFirst($TS::Descendants, (Both (NameIs "Prompt") (TypeIs $CT::Edit)))
    if ($prompt) { $prompt.SetFocus() }
    if ($Action -eq "send" -and $TextFile -and (Test-Path $TextFile)) {
        if (-not $prompt) { throw "prompt box not found" }
        $text = [IO.File]::ReadAllText($TextFile, [Text.Encoding]::UTF8)
        $old = $null
        try { $old = [System.Windows.Forms.Clipboard]::GetText() } catch {}
        [System.Windows.Forms.Clipboard]::SetText($text)
        Start-Sleep -Milliseconds 120
        [System.Windows.Forms.SendKeys]::SendWait("^v")
        Start-Sleep -Milliseconds 250
        [System.Windows.Forms.SendKeys]::SendWait("{ENTER}")
        Start-Sleep -Milliseconds 300
        if ($old) { try { [System.Windows.Forms.Clipboard]::SetText($old) } catch {} }
    }
    Log "ok $Action $Mode $Title"
} catch {
    Log ("error: " + $_.Exception.Message + " @" + $_.InvocationInfo.ScriptLineNumber)
    $failed = $true
} finally {
    # 보낼 글이 담긴 임시 파일은 성공·실패와 상관없이 지운다
    if ($TextFile) { Remove-Item $TextFile -ErrorAction SilentlyContinue }
}
if ($failed) { exit 1 }
