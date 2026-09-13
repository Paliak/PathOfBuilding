package.path = "runtime/lua/?.lua;" .. package.path
local json = require("dkjson")
local base64 = require("base64")
local zlib = require("zlib")
local BASE_BRANCH_SHA = os.getenv("BASE_BRANCH_SHA")
local input = assert(io.open("/cache/corpus_" .. BASE_BRANCH_SHA .. ".json", "r"))
local corpus = assert(json.decode(input:read("*a")))
assert(corpus.schemaVersion == 2 and #corpus.builds > 0 and #corpus.builds == corpus.count, "Invalid build corpus")

local filePath = "/cache/"

for _, testBuild in ipairs(corpus.builds) do
    local xml = zlib.inflate()(base64.decode(testBuild.code:gsub("-", "+"):gsub("_", "/")))
	local startTime = GetTime()

    -- Compute the build
    print("[+] Computing " .. testBuild.sha256)
    loadBuildFromXML(xml)
    local calcDuration = GetTime() - startTime
    print("[-] Computed in " .. calcDuration .. "ms")

	local fileName = testBuild.sha256 .. "_" .. BASE_BRANCH_SHA
	
    -- Save the computed build xml. Include full minion and player outputs.
    local buildHnd = io.open(filePath .. fileName .. ".build", "w+")
    buildHnd:write(build:SaveDB("Cache", {fullPlayerStat = true, fullMinionStat = true} ))
    buildHnd:close()

    -- Save the amount of time calculation of this build took
    local timeHnd = io.open(filePath .. fileName .. ".time", "w+")
    timeHnd:write(calcDuration)
    timeHnd:close()
end
