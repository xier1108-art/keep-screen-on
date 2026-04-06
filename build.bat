@echo off
chcp 65001 > nul
echo.
echo ====================================================
echo   화면안꺼지게 EXE 빌드
echo ====================================================
echo.

python -c "import PyInstaller" 2>nul
if errorlevel 1 (
    echo [설치 중] PyInstaller 설치...
    pip install pyinstaller
)

python -c "import pystray, PIL" 2>nul
if errorlevel 1 (
    echo [설치 중] pystray, Pillow 설치...
    pip install pystray Pillow
)

echo.
echo [빌드 중] 화면안꺼지게.exe 생성 중...
echo.
pyinstaller 화면안꺼지게.spec --noconfirm

if errorlevel 1 (
    echo.
    echo [오류] 빌드 실패. 위 메시지를 확인하세요.
    pause
    exit /b 1
)

echo.
echo ====================================================
echo   완료! dist\화면안꺼지게.exe 에 저장되었습니다.
echo   단축키: Ctrl+Shift+K (토글)
echo ====================================================
echo.
pause
