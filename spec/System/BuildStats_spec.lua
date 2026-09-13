describe("Full build stat export", function()
	local appendStats = dofile("../spec/BuildStats.lua")
	it("keeps both nested stat paths and minion stats", function()
		local xml = { { elem = "PlayerStat", attrib = { stat = "Life", value = "100" } } }
		local output = { Life = 100, MainHand = { Damage = 10 }, OffHand = { Damage = 20 }, Minion = { Life = 50 } }
		appendStats(xml, output, "PlayerStat")
		appendStats(xml, output.Minion, "MinionStat")
		assert.same({
			{ elem = "PlayerStat", attrib = { stat = "Life", value = "100" } },
			{ elem = "PlayerStat", attrib = { stat = "MainHand.Damage", value = "10" } },
			{ elem = "PlayerStat", attrib = { stat = "OffHand.Damage", value = "20" } },
			{ elem = "MinionStat", attrib = { stat = "Life", value = "50" } },
		}, xml)
	end)
	it("avoids runtime object references and cycles without dropping shared stats", function()
		local object = { internal = 99 }
		object.Object = object
		local shared = { Damage = 10 }
		local output = { A = shared, B = shared, ObjectReference = object, Requirement = { value = 42, sourceItem = object, sourceGem = { internal = 99 } }, [object] = true }
		output.Cycle = output
		local xml = {}
		appendStats(xml, output, "PlayerStat")
		assert.same({
			{ elem = "PlayerStat", attrib = { stat = "A.Damage", value = "10" } },
			{ elem = "PlayerStat", attrib = { stat = "B.Damage", value = "10" } },
			{ elem = "PlayerStat", attrib = { stat = "Requirement.value", value = "42" } },
		}, xml)
	end)
end)
