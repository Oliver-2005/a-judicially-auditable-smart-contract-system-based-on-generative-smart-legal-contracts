@echo off
set "PATH=D:\visual\MSBuild\Microsoft\VisualStudio\NodeJs;%PATH%"
cd /d "%~dp0"
call npx hardhat test
