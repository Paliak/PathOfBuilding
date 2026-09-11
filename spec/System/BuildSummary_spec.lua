describe("Build comparison summary", function()
	local summarize = dofile("../spec/BuildSummary.lua")
	local function lines(text)
		return (text .. "\n"):gmatch("([^\n]*)\n")
	end
	it("reports identical calculations without a mismatch", function()
		local output, changed = summarize(lines(""), 5, "base", "head")
		assert.equals(0, changed)
		assert.matches("No calculated-stat differences found", output, 1, true)
		assert.matches("Compared **5 builds**", output, 1, true)
	end)
	it("counts affected builds once and keeps player, minion and missing values", function()
		local output, changed = summarize(lines([[## Output Diff for A.build
Life Mismatch in player outputs:
	head Output: 118
	dev Output: 92
Life Mismatch in minion outputs:
	head Output: 20
	dev Output: nil
## Output Diff for B.build
Life Mismatch in player outputs:
	head Output: 200
	dev Output: 100]]), 5, "base", "head")
		assert.equals(2, changed)
		assert.matches("3 changed values", output, 1, true)
		assert.matches("| player.Life | 2 | A | 92 | 118 |", output, 1, true)
		assert.matches("| minion.Life | 1 | A | nil | 20 |", output, 1, true)
	end)
	it("limits display rows without dropping mismatches and escapes table content", function()
		local input = { "## Output Diff for A|<B>.build" }
		for index = 1, 30 do
			input[#input + 1] = string.format("Stat%d Mismatch in player outputs:\n\thead Output: 2\n\tdev Output: 1", index)
		end
		local output, changed = summarize(lines(table.concat(input, "\n")), 1, "base", "head")
		assert.equals(1, changed)
		assert.matches("Showing 25 of 30 changed stats", output, 1, true)
		assert.matches("30 changed values", output, 1, true)
		assert.matches("A&#124;&lt;B&gt;", output, 1, true)
	end)
	it("rejects a truncated difference instead of reporting a clean comparison", function()
		assert.has_error(function()
			summarize(lines("## Output Diff for A.build\nLife Mismatch in player outputs:\n"), 1, "base", "head")
		end)
	end)
end)
