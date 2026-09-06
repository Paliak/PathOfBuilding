local inputListPath = assert(arg[1], "Input list is required")
package.path = "../runtime/lua/?.lua;../runtime/lua/?/init.lua;" .. package.path
local originalDofile = dofile
function dofile(path)
    if path == "Launch.lua" then originalDofile("/harness/HeadlessSupport.lua") end
    return originalDofile(path)
end
dofile("HeadlessWrapper.lua")
dofile = originalDofile
assert(loadBuildFromXML, "Headless initialization failed")
-- PoB's UI loader can report a failed import without throwing. Make those
-- failures fatal before stale/default calculations can be saved as success.
local originalLoadDB = build.LoadDB
function build:LoadDB(...)
    assert(not originalLoadDB(self, ...), "Build XML import failed")
end
function launch:ShowErrMsg(message, ...) error(string.format(message, ...)) end
local list = assert(io.open(inputListPath, "r"))
local posix = require("posix")
posix.signal(posix.SIGALRM, function() error("Build calculation deadline exceeded") end)
local count = 0
for filename in list:lines() do
    assert(filename:match("^[%w%-]+%.xml$"), "Invalid staged input name")
    local input = assert(io.open("/inputs/" .. filename, "rb"))
    local xml = input:read("*a")
    input:close()
    print("Calculating input " .. filename)
    posix.alarm(30)
    loadBuildFromXML(xml, filename)
    assert(build.buildName == filename and build.targetVersion, "Build initialization incomplete")
    assert(build and build.calcsTab and build.calcsTab.mainOutput, "Missing calculated output")
    local saved = assert(build:SaveDB("CI"))
    assert(saved:find("<PlayerStat ", 1, true), "Empty player output")
    if build.calcsTab.mainEnv.minion then
        assert(saved:find("<MinionStat ", 1, true), "Empty active minion output")
    end
    posix.alarm(0)
    local output = assert(io.open("/outputs/" .. filename .. ".build", "wb"))
    output:write(saved)
    output:close()
    count = count + 1
end
list:close()
print("Calculated and saved " .. count .. " inputs")
