; NSIS customisation for 智绘生物
; Called by electron-builder during NSIS script generation.

!macro customInstall
  ; Create a desktop shortcut in addition to the Start Menu entry.
  ; electron-builder already does this but we force overwrite to keep name consistent.
!macroend

!macro customUnInstall
  ; On uninstall, ask whether to wipe %APPDATA%/智绘生物 (contains downloaded models + DB).
  MessageBox MB_YESNO|MB_ICONQUESTION "是否同时删除用户数据？$\r$\n$\r$\n包含已下载的模型（约 2.3 GB）、知识库、向量数据库。$\r$\n$\r$\n选择『否』将保留数据，方便下次重装。" IDNO skipUserData
  RMDir /r "$APPDATA\智绘生物"
  skipUserData:
!macroend
