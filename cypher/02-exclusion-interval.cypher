// Does a material sit inside a provision the rule excludes?
//
// $material_norm is the material's code normalised to the eight digit space the
// rules use, so a fully classified material is one comparison against the
// interval the rule row carries.  `inside_group` is the answer for that code.
//
// The engine asks the same question in Python rather than here, because a
// material may be written coarser than the interval: heading 8504 covers
// 8504.00 to 8504.99, so it sits neither inside nor outside 8504.10 to 8504.50
// and the honest answer is that the exporter has not said enough.  That third
// answer is what a normalised code cannot show.
MATCH (r:OriginRule {id: $rule})
WITH r, $material_norm AS material
RETURN material >= r.group_exclude_from AND material <= r.group_exclude_to AS inside_group,
       r.group_exclude_from AS from_code, r.group_exclude_to AS to_code;
