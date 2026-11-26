@echo off
rem Validacion en red real (TRL 5): ping ICMP real cada 30 s a equipos de la LAN.
cd /d "%~dp0.."
set NETGUARD_INVENTORY=demo\inventario_lab.csv
set NETGUARD_DB_PATH=demo\netguard_lab.sqlite3
set PING_INTERVAL_SECONDS=30
set PING_TARGETS=[{"device_ip":"172.16.30.161","target_ip":"172.16.30.161"},{"device_ip":"172.26.176.1","target_ip":"172.26.176.1"},{"device_ip":"172.26.176.250","target_ip":"172.26.176.250"}]
npm run dev
