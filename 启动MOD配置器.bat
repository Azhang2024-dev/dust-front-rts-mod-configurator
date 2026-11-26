@echo off
chcp 65001 >nul
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
pushd "%SCRIPT_DIR%"
if errorlevel 1 goto :err_cd

set "PY_EXE="
set "PYW_EXE="

rem 1. Try uv python find 3.12
where uv >nul 2>nul
if not errorlevel 1 call :try_uv_cmd uv
if not defined PY_EXE if exist "%USERPROFILE%\.local\bin\uv.exe" call :try_uv_cmd "%USERPROFILE%\.local\bin\uv.exe"

rem 2. Try WindowsApps aliases without Store version number
if not defined PY_EXE call :check_candidate "%LOCALAPPDATA%\Microsoft\WindowsApps\python3.12.exe"
if not defined PY_EXE call :check_candidate "%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe"

rem 3. Wildcard scan Program Files\WindowsApps\PythonSoftwareFoundation.Python.3.12_*
if not defined PY_EXE if exist "%ProgramFiles%\WindowsApps" call :scan_store_windowsapps

rem 4. Fallback to py launcher and PATH python
if not defined PY_EXE call :try_py_launcher -3.12
if not defined PY_EXE call :try_py_launcher -3
if not defined PY_EXE call :try_where_python

if not defined PY_EXE goto :err_no_python

rem Resolve matching pythonw for windowless GUI launch
call :resolve_pythonw "%PY_EXE%"

if not "%~1"=="" goto :run_with_args

"%PY_EXE%" -m mod_configurator.main --check >nul
if errorlevel 1 goto :err_selfcheck

if defined PYW_EXE goto :launch_gui_w
"%PY_EXE%" -m mod_configurator.main
if errorlevel 1 pause
popd
exit /b 0

:launch_gui_w
start "" "%PYW_EXE%" -m mod_configurator.main
popd
exit /b 0

:run_with_args
"%PY_EXE%" -m mod_configurator.main %*
set "RC=%ERRORLEVEL%"
popd
exit /b %RC%

:try_uv_cmd
if defined PY_EXE goto :eof
for /f "usebackq delims=" %%P in (`"%~1" python find 3.12 2^>nul`) do call :check_candidate "%%P"
goto :eof

:scan_store_windowsapps
if defined PY_EXE goto :eof
for /f "delims=" %%D in ('dir /b /ad /o-n "%ProgramFiles%\WindowsApps\PythonSoftwareFoundation.Python.3.12_*" 2^>nul') do call :check_candidate "%ProgramFiles%\WindowsApps\%%D\python3.12.exe"
goto :eof

:try_py_launcher
if defined PY_EXE goto :eof
for /f "usebackq delims=" %%P in (`py %~1 -c "import sys; print(sys.executable)" 2^>nul`) do call :check_candidate "%%P"
goto :eof

:try_where_python
if defined PY_EXE goto :eof
for /f "usebackq delims=" %%P in (`where python 2^>nul`) do call :check_candidate "%%P"
goto :eof

:check_candidate
if defined PY_EXE goto :eof
set "CAND=%~1"
if "%CAND%"=="" goto :eof
if not exist "%CAND%" goto :eof
"%CAND%" -c "import sys, tkinter; assert sys.version_info >= (3, 12)" >nul 2>nul
if not errorlevel 1 set "PY_EXE=%CAND%"
goto :eof

:resolve_pythonw
if exist "%LOCALAPPDATA%\Microsoft\WindowsApps\pythonw3.12.exe" (
    "%LOCALAPPDATA%\Microsoft\WindowsApps\pythonw3.12.exe" -c "import sys, tkinter; assert sys.version_info >= (3, 12)" >nul 2>nul
    if not errorlevel 1 set "PYW_EXE=%LOCALAPPDATA%\Microsoft\WindowsApps\pythonw3.12.exe"
)
if defined PYW_EXE goto :eof
if exist "%~dp1pythonw3.12.exe" set "PYW_EXE=%~dp1pythonw3.12.exe"
if not defined PYW_EXE if exist "%~dp1pythonw.exe" set "PYW_EXE=%~dp1pythonw.exe"
goto :eof

:err_cd
echo [错误] 无法切换到工作目录: "%SCRIPT_DIR%"
pause
exit /b 1

:err_no_python
echo [错误] 未能在本机找到可用的 Python 3.12+ 解释器（且需包含 tkinter 模块）。
echo 请安装 Python 3.12 并勾选 tcl/tk 组件后重试。
pause
popd
exit /b 1

:err_selfcheck
echo [错误] 配置器自检未通过，详细报错如下：
"%PY_EXE%" -m mod_configurator.main --check
pause
popd
exit /b 1
