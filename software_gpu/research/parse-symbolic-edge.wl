ClearAll[ARETaskGraph, ARETask, probe];
source = "ARETaskGraph[\n ARETask[\"ax\",\"input\",{}, {0,0,0,0},\"f32\",{2,2,3}],\n ARETask[\"ay\",\"input\",{}, {0,0,0,1},\"f32\",{2,2,3}],\n ARETask[\"bx\",\"input\",{}, {0,0,0,2},\"f32\",{2,2,3}],\n ARETask[\"by\",\"input\",{}, {0,0,0,3},\"f32\",{2,2,3}],\n ARETask[\"px\",\"input\",{}, {0,0,0,4},\"f32\",{2,2,3}],\n ARETask[\"py\",\"input\",{}, {0,0,0,5},\"f32\",{2,2,3}],\n ARETask[\"dx\",\"sub\",{\"bx\",\"ax\"}, {1,0,0,0},\"f32\",{2,2,3}],\n ARETask[\"dy\",\"sub\",{\"by\",\"ay\"}, {1,0,0,1},\"f32\",{2,2,3}],\n ARETask[\"rx\",\"sub\",{\"px\",\"ax\"}, {1,0,0,2},\"f32\",{2,2,3}],\n ARETask[\"ry\",\"sub\",{\"py\",\"ay\"}, {1,0,0,3},\"f32\",{2,2,3}],\n ARETask[\"left\",\"mul\",{\"rx\",\"dy\"}, {2,0,0,0},\"f32\",{2,2,3}],\n ARETask[\"right\",\"mul\",{\"ry\",\"dx\"}, {2,0,0,1},\"f32\",{2,2,3}],\n ARETask[\"edge\",\"sub\",{\"left\",\"right\"}, {3,0,0,0},\"f32\",{2,2,3}]\n]";
held = Quiet[Check[ToExpression[source, InputForm, HoldComplete], $Failed]];
valid = MatchQ[held, HoldComplete[ARETaskGraph[ARETask[_String,_String,{___String},{__Integer},_String,{__Integer}]..]]];
probe = 0; heldEffect = ToExpression["probe = 99", InputForm, HoldComplete];
colors = <|"input"->"gray","sub"->"blue","mul"->"orange"|>;
nodes = If[valid, Cases[held, ARETask[id_String, op_String, deps:{___String}, point:{__Integer}, dtype_String, shape:{__Integer}] :>
<|"id"->id,"op"->op,"deps"->deps,"point"->point,"dtype"->dtype,"shape"->shape,"color"->colors[op],"contract"->"ordered-f32-v1"|>, Infinity], {}];
done = Lookup[Select[nodes,#["op"]==="input"&],"id"];
pending = Select[nodes,#["op"]=!="input"&]; waves={};
While[pending=!={}, ready=Select[pending,And@@(MemberQ[done,#]& /@ #["deps"])&];
If[ready==={},Break[]]; groups=GatherBy[ready,{#["op"],#["dtype"],#["shape"],#["contract"]}&];
AppendTo[waves,Lookup[#,"id"]& /@ groups]; done=Join[done,Lookup[ready,"id"]];
pending=Select[pending,!MemberQ[done,#["id"]]&]];
symbolic=<|"ax"->ax,"ay"->ay,"bx"->bx,"by"->by,"px"->px,"py"->py|>;
Do[Do[node=SelectFirst[nodes,#["id"]===id&]; args=Lookup[symbolic,node["deps"]];
symbolic[id]=Switch[node["op"],"sub",Subtract@@args,"mul",Times@@args],{id,Flatten[wave]}],{wave,waves}];
exactIdentity = Expand[symbolic["edge"]-((px-ax)*(by-ay)-(py-ay)*(bx-ax))]===0;
ExportString[<|"protocol"->"are.symbolic-wave-ir.v1","parser"->"Wolfram ToExpression InputForm HoldComplete","syntax_valid"->valid,"held_assignment_did_not_execute"->(probe===0),"nodes"->nodes,"outputs"->{"edge"},"wolfram_waves"->waves,"symbolic_edge_identity"->exactIdentity|>,"RawJSON"]
