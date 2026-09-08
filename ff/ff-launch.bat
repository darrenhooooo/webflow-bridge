@echo off
rem ============================================================
rem  Webflow Bridge for Firefox - Windows launcher (P0)
rem  Opens the user's REAL Firefox profile with the BiDi remote
rem  debugging port 9222 so the ff daemon can drive it.
rem  Never creates or copies a profile.
rem
rem  Profile selection priority from profiles.ini:
rem    rule 1: [Install*] section Default=Profiles/xxx
rem            the profile this Firefox install actually uses
rem    rule 2: a [Profile*] section whose Name is default-release
rem    rule 3: the legacy Default=1 marker as last resort
rem  The chosen name / path / source rule is printed.
rem
rem  NOTE: never put unquoted ASCII parentheses inside echo
rem  text of an if/for block - cmd treats them as block syntax.
rem ============================================================
setlocal enabledelayedexpansion
chcp 65001 >nul
title Webflow Bridge - Firefox Launcher

set "FFROOT=%APPDATA%\Mozilla\Firefox"
set "INI=%FFROOT%\profiles.ini"

rem ---- locate firefox.exe, 64-bit preferred then x86 ----------------
set "FIREFOX=C:\Program Files\Mozilla Firefox\firefox.exe"
if not exist "%FIREFOX%" set "FIREFOX=C:\Program Files (x86)\Mozilla Firefox\firefox.exe"
if not exist "%FIREFOX%" (
  echo [ff-launch] error: firefox.exe not found in either Program Files path.
  exit /b 1
)
if not exist "%INI%" (
  echo [ff-launch] error: profiles.ini not found at %INI%
  exit /b 1
)

rem ---- idempotency: port 9222 already in BiDi mode? --------------------
netstat -ano | findstr /C:":9222" | findstr /C:"LISTENING" >nul 2>&1
if not errorlevel 1 (
  echo [ff-launch] Firefox 已在调试模式运行，port 9222 已监听，无需重复启动。
  exit /b 0
)

rem ---- Firefox process exists but 9222 not listening? ------------------
tasklist /FI "IMAGENAME eq firefox.exe" 2>nul | findstr /I "firefox.exe" >nul
if not errorlevel 1 (
  echo [ff-launch] 检测到 Firefox 已在运行，但 9222 端口未监听。
  echo [ff-launch] 请先关闭 Firefox，再用本启动器打开，单实例限制。
  exit /b 1
)

rem ---- parse profiles.ini ----------------------------------------------
set "CUR="
set "P_NAME="
set "P_PATH="
set "P_DEF="
set "INSTALL_DEF="
set "INSTALL_NAME="
set "DR_NAME="
set "DR_PATH="
set "OLD_NAME="
set "OLD_PATH="

for /f "usebackq delims=" %%L in (`type "%INI%" ^& echo [__EOF__]`) do (
  set "L=%%L"
  set "C0=!L:~0,1!"
  if "!C0!"=="[" (
    rem ---- leaving the current section ---------------------------
    if defined CUR (
      if /i "!CUR:~0,7!"=="Profile" (
        if defined P_NAME (
          if /i "!P_NAME!"=="default-release" (
            set "DR_NAME=!P_NAME!"
            set "DR_PATH=!P_PATH!"
          )
        )
        if defined INSTALL_DEF (
          if /i "!P_PATH!"=="!INSTALL_DEF!" (
            set "INSTALL_NAME=!P_NAME!"
          )
        )
        if /i "!P_DEF!"=="1" (
          set "OLD_NAME=!P_NAME!"
          set "OLD_PATH=!P_PATH!"
        )
      )
    )
    rem ---- begin the new section ---------------------------------
    set "CUR="
    set "P_NAME="
    set "P_PATH="
    set "P_DEF="
    set "S=!L:~1!"
    if defined S set "S=!S:~0,-1!"
    if /i "!S:~0,7!"=="Install" (
      set "CUR=!S!"
    ) else (
      if /i "!S:~0,7!"=="Profile" (
        set "D8=!S:~7,1!"
        if defined D8 if "!D8!" GEQ "0" if "!D8!" LEQ "9" set "CUR=!S!"
      )
    )
  ) else (
    rem ---- key line inside the current section -------------------
    if defined CUR (
      for /f "tokens=1,* delims==" %%A in ("!L!") do (
        set "K=%%A"
        set "V=%%B"
      )
      if /i "!CUR:~0,7!"=="Install" (
        if /i "!K!"=="Default" (
          set "INSTALL_DEF=!V!"
        )
      ) else (
        if /i "!CUR:~0,7!"=="Profile" (
          if /i "!K!"=="Name" set "P_NAME=!V!"
          if /i "!K!"=="Path" set "P_PATH=!V!"
          if /i "!K!"=="Default" set "P_DEF=!V!"
        )
      )
    )
  )
)

rem ---- select the profile, priority rules 1 then 2 then 3 ---------------
set "SEL_NAME="
set "SEL_RAW="
set "SEL_SRC="

rem rule 1: [Install*] section Default value
if defined INSTALL_DEF (
  set "SEL_NAME=!INSTALL_NAME!"
  set "SEL_RAW=!INSTALL_DEF!"
  set "SEL_SRC=规则1: 依据 [Install*] 段 Default 指向"
)
if defined SEL_RAW (
  set "PROFDIR=!SEL_RAW!"
  if not "!PROFDIR:~1,1!"==":" if not "!PROFDIR:~0,2!"=="\\" set "PROFDIR=%FFROOT%\!PROFDIR!"
  if not exist "!PROFDIR!" (
    echo [ff-launch] 规则1 选中的目录不存在，降级尝试: !PROFDIR!
    set "SEL_RAW="
  )
)

rem rule 2: Profile section with Name=default-release
if not defined SEL_RAW (
  if defined DR_PATH (
    set "SEL_NAME=!DR_NAME!"
    set "SEL_RAW=!DR_PATH!"
    set "SEL_SRC=规则2: 依据 Name=default-release"
  )
)
if defined SEL_RAW (
  if not defined SEL_NAME set "SEL_NAME=default-release"
  set "PROFDIR=!SEL_RAW!"
  if not "!PROFDIR:~1,1!"==":" if not "!PROFDIR:~0,2!"=="\\" set "PROFDIR=%FFROOT%\!PROFDIR!"
  if not exist "!PROFDIR!" (
    echo [ff-launch] 规则2 选中的目录不存在，降级尝试: !PROFDIR!
    set "SEL_RAW="
  )
)

rem rule 3: legacy Default=1 marker
if not defined SEL_RAW (
  if defined OLD_PATH (
    set "SEL_NAME=!OLD_NAME!"
    set "SEL_RAW=!OLD_PATH!"
    set "SEL_SRC=规则3: 旧式 Default=1 标记兜底"
  )
)
if defined SEL_RAW (
  set "PROFDIR=!SEL_RAW!"
  if not "!PROFDIR:~1,1!"==":" if not "!PROFDIR:~0,2!"=="\\" set "PROFDIR=%FFROOT%\!PROFDIR!"
  if not exist "!PROFDIR!" (
    echo [ff-launch] error: 兜底 profile 目录也不存在: !PROFDIR!
    set "SEL_RAW="
  )
)

if not defined SEL_RAW (
  echo [ff-launch] error: 未找到可用 profile，请检查 %INI%
  exit /b 1
)
if not defined SEL_NAME (
  for %%N in ("!SEL_RAW!") do set "SEL_NAME=%%~nxN"
)

echo [ff-launch] 选择的 profile: !SEL_NAME!
echo [ff-launch] profile 路径     : !PROFDIR!
echo [ff-launch] 来源规则         : !SEL_SRC!

rem ---- launch -----------------------------------------------------------
echo [ff-launch] 启动 Firefox ... 调试端口 9222
start "" "%FIREFOX%" -profile "!PROFDIR!" --remote-debugging-port 9222 -remote-allow-system-access

rem ---- wait for the remote agent, up to about 30 seconds -----------------
set /a N=0
:waitloop
set /a N+=1
if !N! gtr 30 (
  echo [ff-launch] 警告: 30 秒内 9222 端口未监听。
  echo [ff-launch] 若 Firefox 提示 profile 正在使用，请先关闭已开的 Firefox 再重试。
  echo [ff-launch] 若窗口已出现，可稍等后检查: netstat -ano ^| findstr :9222
  exit /b 1
)
netstat -ano | findstr /C:":9222" | findstr /C:"LISTENING" >nul 2>&1
if not errorlevel 1 goto waitok
ping -n 2 127.0.0.1 >nul
goto waitloop

:waitok
echo [ff-launch] 9222 已监听。可运行 ff daemon 并 POST /command。
endlocal
exit /b 0
