-- Use the same test exporter on both revisions, including bases whose normal
-- SaveDB does not support the old fullPlayerStat/fullMinionStat options.
local appendStats = dofile("../spec/BuildStats.lua")
local saveBuild = build.Save
function build:Save(xml)
	saveBuild(self, xml)
	appendStats(xml, self.calcsTab.mainOutput, "PlayerStat")
	if self.calcsTab.mainOutput.Minion then
		appendStats(xml, self.calcsTab.mainOutput.Minion, "MinionStat")
	end
end

-- The API adapter supplies local XML files. A missing file is a failed test,
-- not a reason to try another download provider or silently skip the build.
local inputs = {}
if os.getenv("BUILDLINKS") then
	local list = assert(io.open(os.getenv("BUILDLINKS"), "r"))
	for name in list:lines() do
		name = name:gsub("\r$", "")
		assert(#name == 64 and name:match("^%x+$"), "Invalid corpus build name")
		inputs[#inputs + 1] = { filename = name, path = assert(os.getenv("CACHEDIR")) .. "/" .. name .. ".xml" }
	end
	list:close()
else
	for name in lfs.dir("../spec/TestBuilds") do
		if name:match("%.xml$") then
			inputs[#inputs + 1] = { filename = name, path = "../spec/TestBuilds/" .. name }
		end
	end
end

for _, input in ipairs(inputs) do
	local file = assert(io.open(input.path, "r"))
	local xml = file:read("*a")
	file:close()
	local document, err = common.xml.ParseXML(xml)
	assert(document and not err and document[1] and document[1].elem == "PathOfBuilding", "Invalid build XML: " .. input.filename)
	local filePath = (os.getenv("BUILDCACHEPREFIX") or "/tmp") .. "/" .. input.filename
	local startTime = GetTime()
	print("[+] Computing " .. filePath)
	loadBuildFromXML(xml)
	assert(not build.abortSave and type(build.calcsTab.mainOutput.Life) == "number", "No calculated output: " .. input.filename)
	local calcDuration = GetTime() - startTime
	print("[-] Computed " .. filePath .. " in " .. calcDuration .. "ms")

	local saved = assert(build:SaveDB("Cache"), "Could not save " .. input.filename)
	local buildFile = assert(io.open(filePath .. ".build", "w"))
	buildFile:write(saved)
	buildFile:close()
	local timeFile = assert(io.open(filePath .. ".time", "w"))
	timeFile:write(calcDuration)
	timeFile:close()
end
