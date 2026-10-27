# HASS.Agent on a Windows computer: its sensors and commands, the same every time. HASS.Agent itself
# comes from winget (winget install --id Hass.Agent --exact) and its first-run setup takes the
# Home Assistant address, a long-lived token and an MQTT login, all typed in on the computer. Two
# things to get right there: call the device "Computer" (every entity the house uses is
# sensor.computer_... and so on, docs/devices.md), and write the address with its port, like
# http://homeassistant.local:80. Home Assistant answers on 80 on this install, and HASS.Agent quietly
# assumes 8123 when there's no port in it. This only copies sensors.json and commands.json into its
# config, with fixed ids so Home Assistant keeps the same entities, and restarts it. A house folder
# with its own pc/hass-agent/ (tools/house.py) wins, for a computer with commands of its own, like
# a "Sound to the monitor" button for the monitor's name in house.toml
$ErrorActionPreference = "Stop"
$config = Join-Path $env:LOCALAPPDATA "HASS.Agent\Client\config"
$exe = Join-Path $env:LOCALAPPDATA "HASS.Agent\Client\HASS.Agent.exe"
if (-not (Test-Path $config)) { throw "HASS.Agent isn't set up yet, run its first-run setup first" }

$source = Join-Path $PSScriptRoot "hass-agent"
$house = (& python (Join-Path $PSScriptRoot "..\tools\house.py") where 2>$null)
if ($house -and (Test-Path (Join-Path $house "pc\hass-agent\sensors.json"))) { $source = Join-Path $house "pc\hass-agent" }

Get-Process -Name "HASS.Agent" -ErrorAction SilentlyContinue | Stop-Process -Confirm:$false
Start-Sleep -Seconds 3
Copy-Item (Join-Path $source "sensors.json") $config -Force
Copy-Item (Join-Path $source "commands.json") $config -Force
Start-Process -FilePath $exe
Write-Output "HASS.Agent restarted with $((Get-Content (Join-Path $config 'sensors.json') -Raw | ConvertFrom-Json).Count) sensors"
