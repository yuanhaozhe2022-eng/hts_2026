-- PocketWheel helper for BeamNG.drive.
--
-- OutGauge only sends a gear number, and BeamNG's automatics report Park and Neutral both
-- as 0, so the phone can't show "P". This tiny protocol sends what the in-game dash shows
-- (P, R, N, D, S3, M2, or the number in a manual) plus the engine's real redline to the
-- PocketWheel server, next to the OutGauge data.
--
-- BeamNG runs it when Options > Other > "Other protocols" is enabled.
-- Install with:  python main.py --install-beamng-mod

local M = {}

local function init() end
local function reset() end
local function getAddress()        return "127.0.0.1" end
local function getPort()           return 4445 end
local function getMaxUpdateRate()  return 30 end
local function isPhysicsStepUsed() return false end

local function getStructDefinition()
  return [[
    char  magic[4];   // "PWG1"
    char  gear[8];    // gear as the car's dash shows it
    float maxrpm;     // redline, 0 if unknown
  ]]
end

local function fillStruct(o, dtSim)
  o.magic = "PWG1"
  o.gear = tostring(electrics.values.gear or "")
  o.maxrpm = electrics.values.maxrpm or 0
end

M.init = init
M.reset = reset
M.getAddress = getAddress
M.getPort = getPort
M.getMaxUpdateRate = getMaxUpdateRate
M.getStructDefinition = getStructDefinition
M.fillStruct = fillStruct
M.isPhysicsStepUsed = isPhysicsStepUsed

return M
