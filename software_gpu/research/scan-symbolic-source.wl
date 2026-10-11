(* Offline scanner for our finite task grammar. Never ReleaseHold input. *)
ClearAll[ARETaskGraph, ARETask, AREScanSource];
AREScanSource[source_String, outputs_List] := Module[
  {held, nodes, ids, byId, colors, done, pending, ready, groups, waves = {}, fail},
  fail[reason_] := <|"scan_status" -> "BLOCKED", "reason" -> reason|>;
  If[StringLength[source] > 65536, Return[fail["SOURCE_BUDGET"]]];
  held = Quiet[Check[ToExpression[source, InputForm, HoldComplete], $Failed]];
  If[!MatchQ[held, HoldComplete[ARETaskGraph[
      ARETask[_String,_String,{___String},{__Integer},_String,{__Integer}]..]]],
    Return[fail["TASK_GRAMMAR"]]];
  colors = <|"input"->"gray", "add"->"green", "sub"->"blue", "mul"->"orange"|>;
  nodes = Cases[held, ARETask[id_String, op_String, deps:{___String},
      point:{__Integer}, dtype_String, shape:{__Integer}] :>
    <|"id"->id, "op"->op, "deps"->deps, "point"->point, "dtype"->dtype,
      "shape"->shape, "color"->Lookup[colors,op,"unknown"], "contract"->"ordered-f32-v1"|>, Infinity];
  If[!1 <= Length[nodes] <= 128, Return[fail["NODE_BUDGET"]]];
  ids = Lookup[nodes,"id"];
  If[Length[DeleteDuplicates[ids]] != Length[ids] ||
      !And@@(StringMatchQ[#,RegularExpression["[a-z][a-z0-9_]{0,31}"]]& /@ ids),
    Return[fail["IDENTITIES"]]];
  If[!And@@(MemberQ[Keys[colors],#["op"]] && #["dtype"] === "f32" &&
      Length[#["deps"]] === If[#["op"] === "input",0,2]& /@ nodes),
    Return[fail["OPERATOR_CONTRACT"]]];
  If[!And@@(1 <= Length[#["point"]] <= 8 && 1 <= Length[#["shape"]] <= 4 &&
      And@@(0 <= # <= 65536& /@ #["point"]) &&
      And@@(1 <= # <= 65536& /@ #["shape"])& /@ nodes) ||
      Length[DeleteDuplicates[Length[#["point"]]& /@ nodes]] != 1,
    Return[fail["DIMENSIONS"]]];
  If[Total[Times@@#["shape"]& /@ nodes] > 1048576, Return[fail["CELL_BUDGET"]]];
  byId = AssociationThread[ids,nodes];
  If[!And@@(With[{n=#},And@@(MemberQ[ids,#] && byId[#]["shape"] === n["shape"]& /@ n["deps"])]& /@ nodes),
    Return[fail["DEPENDENCY_TYPE"]]];
  If[outputs === {} || Length[DeleteDuplicates[outputs]] != Length[outputs] ||
      !And@@(StringQ[#] && MemberQ[ids,#]& /@ outputs), Return[fail["OUTPUTS"]]];
  done = Lookup[Select[nodes,#["op"] === "input"&],"id"];
  pending = Select[nodes,#["op"] =!= "input"&];
  While[pending =!= {},
    ready = SortBy[Select[pending,And@@(MemberQ[done,#]& /@ #["deps"])&],#["id"]&];
    If[ready === {}, Return[fail["CYCLE"]]];
    groups = GatherBy[ready,{#["op"],#["dtype"],#["shape"],#["contract"]}&];
    AppendTo[waves,Lookup[#,"id"]& /@ groups];
    done = Join[done,Lookup[ready,"id"]];
    pending = Select[pending,!MemberQ[done,#["id"]]&]];
  <|"protocol"->"are.symbolic-wave-ir.v1", "scan_status"->"PASS",
    "parser"->"Wolfram ToExpression InputForm HoldComplete", "syntax_valid"->True,
    "nodes"->nodes, "outputs"->outputs, "wolfram_waves"->waves|>]
