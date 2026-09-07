-- Run from the repository root in Dockerfile.test-builds' Linux image.
local function saved(player, minion, reverse)
    local lines = { "<PathOfBuilding><Build>" }
    local function stat(kind, key, value)
        local attrs = reverse and ('value="' .. value .. '" stat="' .. key .. '"')
            or ('stat="' .. key .. '" value="' .. value .. '"')
        table.insert(lines, "<" .. kind .. " " .. attrs .. "/>")
    end
    if player then stat("PlayerStat", "Life", player) end
    if minion then stat("MinionStat", "TotalDPS", minion) end
    table.insert(lines, "</Build></PathOfBuilding>")
    return table.concat(lines, "\n")
end

local cases = {
    { "attribute order", saved(100, 50), saved(100, 50, true), 0 },
    { "player difference", saved(100, 50), saved(101, 50, true), 1 },
    { "minion difference", saved(100, 50), saved(100, 51, true), 1 },
    { "removed minion", saved(100, 50), saved(100, nil, true), 1 },
    { "added minion", saved(100), saved(100, 50, true), 1 },
    { "missing player stats", saved(100), saved(nil, 50, true), 2 },
    { "missing file", saved(100), nil, 2 },
}
for _, case in ipairs(cases) do
    local base, head, log = os.tmpname(), os.tmpname(), os.tmpname()
    local function write(path, value)
        if value then
            local file = assert(io.open(path, "wb"))
            file:write(value)
            file:close()
        else
            os.remove(path)
        end
    end
    write(base, case[2])
    write(head, case[3])
    local status = os.execute("luajit spec/DiffOutput.lua " .. head .. " " .. base .. " > " .. log .. " 2>&1")
    local file = assert(io.open(log, "rb"))
    local details = file:read("*a")
    file:close()
    os.remove(base)
    os.remove(head)
    os.remove(log)
    assert(status == case[4] * 256, case[1] .. ": " .. details)
    print("PASS " .. case[1])
end
print("Passed " .. #cases .. " output comparison tests")
