// Does a material sit inside a provision the rule excludes?
//
// $material_norm is the material's code normalised to the eight digit space the
// rules use, so a fully classified material is one comparison against the
// interval the rule row carries.  `inside_group` is the answer for that code.
//
// This is the single material form of the join the engine actually runs
// (cypher/07-material-against-rule.cypher): the intervals a rule names are
// nodes it points at, and the material list meets them in one traversal.  That
// form sends the span a coarse code can name, so heading 8504 goes in as
// 85040000 to 85049999 and comes back "across" 8504.10 to 8504.50, which is the
// third answer this single comparison cannot show.  This file is kept as the
// one line version a reader can paste when the code is fully classified.
MATCH (r:OriginRule {id: $rule})
WITH r, $material_norm AS material
RETURN material >= r.group_exclude_from AND material <= r.group_exclude_to AS inside_group,
       r.group_exclude_from AS from_code, r.group_exclude_to AS to_code;
