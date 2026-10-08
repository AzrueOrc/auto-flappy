@echo off
cd /d "%~dp0"
if not exist "pixel8a-java\config.local.properties" (
    echo Copy pixel8a-java\config.example.properties to pixel8a-java\config.local.properties and set the mirror rectangle first.
    pause
    exit /b 1
)
set "JAVA_CMD=java"
set "JAVAC_CMD=javac"
where javac >nul 2>nul
if errorlevel 1 (
    if exist "%ProgramFiles%\Android\Android Studio\jbr\bin\javac.exe" (
        set "JAVA_CMD=%ProgramFiles%\Android\Android Studio\jbr\bin\java.exe"
        set "JAVAC_CMD=%ProgramFiles%\Android\Android Studio\jbr\bin\javac.exe"
    ) else (
        echo JDK not found. Install a JDK or Android Studio, then retry.
        pause
        exit /b 1
    )
)
if not exist "build\pixel8a-classes" mkdir "build\pixel8a-classes"
"%JAVAC_CMD%" -d build\pixel8a-classes src\autoflappy\*.java
if errorlevel 1 (
    echo Java compilation failed.
    pause
    exit /b 1
)
"%JAVA_CMD%" -cp build\pixel8a-classes autoflappy.Main --pixel8a
if errorlevel 1 pause
