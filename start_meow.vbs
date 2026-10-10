' meow 启动脚本：用 pythonw 启动，不带黑色控制台窗口
' 双击本文件即可运行。如果报「找不到 pythonw」，请把下面的路径改成你自己的。
Option Explicit

Dim shell, fso, root, pythonw, candidates, i, target
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

root = fso.GetParentFolderName(WScript.ScriptFullName)

' 优先用项目自带的虚拟环境，其次用系统 PATH 里的 pythonw
candidates = Array(root & "\.venv\Scripts\pythonw.exe", "pythonw.exe")
target = ""

For i = 0 To UBound(candidates)
    If InStr(candidates(i), "\") > 0 Then
        If fso.FileExists(candidates(i)) Then
            target = """" & candidates(i) & """"
            Exit For
        End If
    Else
        target = candidates(i)
        Exit For
    End If
Next

If target = "" Then
    MsgBox "没有找到 pythonw.exe。" & vbCrLf & _
           "请先安装 Python，或者在 .venv 里装好依赖。", 16, "meow"
    WScript.Quit 1
End If

shell.CurrentDirectory = root
shell.Run target & " """ & root & "\main.py""", 0, False
