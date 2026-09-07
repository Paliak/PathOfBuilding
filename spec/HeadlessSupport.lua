-- Runtime adapters shared by both revisions, installed just before Launch.lua.
-- Each revision retains its own HeadlessWrapper and production calculation code.
local zlib = require("zlib")
function GetScriptPath() return "/workdir/src" end
function GetRuntimePath() return "/workdir/runtime" end
function GetUserPath() return "/tmp" end
function GetWorkDir() return "/workdir/src" end
function GetTime() return os.clock() * 1000 end
function Inflate(data) return zlib.inflate()(data) end
function Deflate(data) return zlib.deflate()(data) end
