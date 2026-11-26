@echo off
cd /d "%~dp0.."
set NETGUARD_INVENTORY=demo\inventario_demo.csv
set NETGUARD_DB_PATH=demo\netguard_demo.sqlite3
npm run dev
