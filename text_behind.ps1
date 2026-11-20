[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
Add-Type @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public class BehindNative {
 public struct R {public int L,T,Ri,B;}
 public class W {public IntPtr H;public R Bounds;}
 public delegate bool CB(IntPtr h,IntPtr p);
 [DllImport("user32.dll")]static extern bool EnumWindows(CB cb,IntPtr p);
 [DllImport("user32.dll")]static extern bool IsWindowVisible(IntPtr h);
 [DllImport("user32.dll")]static extern bool IsIconic(IntPtr h);
 [DllImport("user32.dll")]static extern bool GetWindowRect(IntPtr h,out R r);
 [DllImport("user32.dll")]static extern uint GetWindowThreadProcessId(IntPtr h,out uint pid);
 [DllImport("user32.dll")]static extern int GetWindowLong(IntPtr h,int i);
 [DllImport("dwmapi.dll")]static extern int DwmGetWindowAttribute(IntPtr h,int a,out int v,int n);
 [DllImport("user32.dll")]static extern IntPtr SetThreadDpiAwarenessContext(IntPtr context);
 public static List<W> List(int ignore) {
  IntPtr old=IntPtr.Zero;
  try{old=SetThreadDpiAwarenessContext(new IntPtr(-4));}catch{}
  var result=new List<W>();
  EnumWindows((h,p)=>{uint id;R r;int cloaked=0;
   GetWindowThreadProcessId(h,out id);
   DwmGetWindowAttribute(h,14,out cloaked,4);
   if(id!=(uint)ignore && cloaked==0 && IsWindowVisible(h) && !IsIconic(h) && (GetWindowLong(h,-20)&32)==0 && GetWindowRect(h,out r) && r.Ri>r.L && r.B>r.T)
    result.Add(new W{H=h,Bounds=r});return true;},IntPtr.Zero);
  if(old!=IntPtr.Zero){try{SetThreadDpiAwarenessContext(old);}catch{}}
  return result;
 }
 public static IntPtr At(List<W> list,double x,double y) {
  foreach(var w in list){var r=w.Bounds;if(x>=r.L && x<r.Ri && y>=r.T && y<r.B)return w.H;}return IntPtr.Zero;
 }
}
"@
$A=[System.Windows.Automation.AutomationElement]
$TP=[System.Windows.Automation.TextPattern]
$walker=[System.Windows.Automation.TreeWalker]::ControlViewWalker
function Intersects($a,$b) {return $a[0] -lt $b[2] -and $a[2] -gt $b[0] -and $a[1] -lt $b[3] -and $a[3] -gt $b[1]}
function Matches($box,$targets,$windows,$handle) {
 foreach($target in $targets){
  $r=$target.rect
  if(Intersects $box $r){
   $x=([Math]::Max($box[0],$r[0])+[Math]::Min($box[2],$r[2]))/2
   $y=([Math]::Max($box[1],$r[1])+[Math]::Min($box[3],$r[3]))/2
   if([BehindNative]::At($windows,$x,$y) -eq $handle){$null=$script:hits.Add([string]$target.id)}
  }
 }
}
while($null -ne ($line=[Console]::ReadLine())) {
 $out=@{ok=$false;hits=@()}
 try {
  $req=$line|ConvertFrom-Json
  $windows=[BehindNative]::List([int]$req.pid)
  $groups=@{}
  foreach($region in $req.regions){
   $r=$region.rect
   foreach($point in @(@((($r[0]+$r[2])/2),(($r[1]+$r[3])/2)),@(($r[0]+3),($r[1]+3)),@(($r[2]-3),($r[1]+3)),@(($r[0]+3),($r[3]-3)),@(($r[2]-3),($r[3]-3)))){
    $h=[BehindNative]::At($windows,$point[0],$point[1]);$key=$h.ToInt64().ToString()
    if($h -ne [IntPtr]::Zero){
     if(-not $groups.ContainsKey($key)){$groups[$key]=@{handle=$h;targets=@()}}
     if($groups[$key].targets -notcontains $region){$groups[$key].targets+= $region}
    }
   }
  }
  $script:hits=New-Object 'System.Collections.Generic.HashSet[string]'
  $budget=[Diagnostics.Stopwatch]::StartNew()
  foreach($group in $groups.Values){
   $stack=New-Object System.Collections.Stack
   try{$stack.Push(@($A::FromHandle($group.handle),0))}catch{continue}
   $visited=0
   while($stack.Count -and $visited -lt 450 -and $budget.ElapsedMilliseconds -lt 1600){
    $pair=$stack.Pop();$node=$pair[0];$depth=[int]$pair[1];$visited++
    try{
     $cur=$node.Current
     if($cur.IsOffscreen){continue}
     $r=$cur.BoundingRectangle
     $box=@($r.Left,$r.Top,$r.Right,$r.Bottom)
     if(-not $r.IsEmpty -and $r.Width -gt 0 -and $r.Height -gt 0){
      $relevant=$false
      foreach($target in $group.targets){if(Intersects $box $target.rect){$relevant=$true;break}}
      if(-not $relevant){continue}
      $pattern=$null;$hasRanges=$false
      if($node.TryGetCurrentPattern($TP::Pattern,[ref]$pattern)){
       foreach($range in $pattern.GetVisibleRanges()){
        if($range.GetText(128) -notmatch '\S'){continue}
        $rects=$range.GetBoundingRectangles()
        for($i=0;$i+3 -lt $rects.Length;$i+=4){
         $textBox=@($rects[$i],$rects[$i+1],($rects[$i]+$rects[$i+2]),($rects[$i+1]+$rects[$i+3]))
         Matches $textBox $group.targets $windows $group.handle
        }
        $hasRanges=$true
       }
      }
      if(-not $hasRanges -and ($cur.ControlType -eq [System.Windows.Automation.ControlType]::Text -or $cur.ClassName -eq 'Static' -or $cur.ClassName -like 'WindowsForms10.STATIC*') -and $cur.Name -match '\S'){
       Matches $box $group.targets $windows $group.handle
      }
     }
     if($depth -lt 16){
      $child=$walker.GetFirstChild($node)
      while($child -and $stack.Count -lt 450){$stack.Push(@($child,($depth+1)));$child=$walker.GetNextSibling($child)}
     }
    }catch{}
   }
  }
  $out.ok=$true;$out.hits=@($script:hits | ForEach-Object {$_})
 } catch {}
 [Console]::Out.WriteLine(($out|ConvertTo-Json -Compress -Depth 4));[Console]::Out.Flush()
}
