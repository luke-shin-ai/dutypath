// Does a material sit inside a provision the rule excludes?
// $group_from and $group_to are normalised codes, so this is one comparison.
MATCH (r:OriginRule {id: $rule})
WITH r, $material_norm AS material
RETURN material >= r.group_exclude_from AND material <= r.group_exclude_to AS inside_group,
       r.group_exclude_from AS from_code, r.group_exclude_to AS to_code;
