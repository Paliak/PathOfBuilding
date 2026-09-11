-- Append calculated stats to the normal saved XML. Item/gem source references
-- describe objects, not calculated stats, and can lead back into the object graph.
return function(xml, output, element)
	local stats, active = {}, {}
	local function collect(values, prefix)
		if active[values] or rawget(values, "Object") == values then return end
		active[values] = true
		for key, value in pairs(values) do
			if type(key) == "string" or type(key) == "number" then
				local name = prefix .. key
				if type(value) == "table" then
					if key ~= "sourceItem" and key ~= "sourceGem" and not (prefix == "" and key == "Minion") then
						collect(value, name .. ".")
					end
				elseif type(value) == "number" or type(value) == "string" or type(value) == "boolean" then
					stats[name] = tostring(value)
				end
			end
		end
		active[values] = nil
	end
	collect(output, "")
	-- Preserve stats already emitted by PoB's normal save path.
	for _, child in ipairs(xml) do
		if child.elem == element then stats[child.attrib.stat] = nil end
	end
	local names = {}
	for name in pairs(stats) do names[#names + 1] = name end
	table.sort(names)
	for _, name in ipairs(names) do
		xml[#xml + 1] = { elem = element, attrib = { stat = name, value = stats[name] } }
	end
end
