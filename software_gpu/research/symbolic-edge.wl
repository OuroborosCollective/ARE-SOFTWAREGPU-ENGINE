ARETaskGraph[
 ARETask["ax","input",{}, {0,0,0,0},"f32",{2,2,3}],
 ARETask["ay","input",{}, {0,0,0,1},"f32",{2,2,3}],
 ARETask["bx","input",{}, {0,0,0,2},"f32",{2,2,3}],
 ARETask["by","input",{}, {0,0,0,3},"f32",{2,2,3}],
 ARETask["px","input",{}, {0,0,0,4},"f32",{2,2,3}],
 ARETask["py","input",{}, {0,0,0,5},"f32",{2,2,3}],
 ARETask["dx","sub",{"bx","ax"}, {1,0,0,0},"f32",{2,2,3}],
 ARETask["dy","sub",{"by","ay"}, {1,0,0,1},"f32",{2,2,3}],
 ARETask["rx","sub",{"px","ax"}, {1,0,0,2},"f32",{2,2,3}],
 ARETask["ry","sub",{"py","ay"}, {1,0,0,3},"f32",{2,2,3}],
 ARETask["left","mul",{"rx","dy"}, {2,0,0,0},"f32",{2,2,3}],
 ARETask["right","mul",{"ry","dx"}, {2,0,0,1},"f32",{2,2,3}],
 ARETask["edge","sub",{"left","right"}, {3,0,0,0},"f32",{2,2,3}]
]
