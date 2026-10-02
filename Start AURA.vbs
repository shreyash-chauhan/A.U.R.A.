Option Explicit

Dim shell, files, projectFolder, pythonwPath
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")

projectFolder = files.GetParentFolderName(WScript.ScriptFullName)
pythonwPath = files.BuildPath(projectFolder, ".venv\Scripts\pythonw.exe")

If Not files.FileExists(pythonwPath) Then
    MsgBox "A.U.R.A.'s Python environment was not found." & vbCrLf & _
           "Open the project folder and install its desktop dependencies first.", _
           vbExclamation, "A.U.R.A. could not start"
    WScript.Quit 1
End If

shell.CurrentDirectory = projectFolder
shell.Run """" & pythonwPath & """ -m aura --desktop", 0, False
