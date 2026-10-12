(* Small, held symbolic control language. Never evaluate input work code. *)
ClearAll[WorkRooms, ParseRoomPlan, RoomWitness];
ParseRoomPlan[source_String] := Module[{held},
  If[StringLength[source] > 4096, Return[$Failed]];
  held = Quiet[Check[ToExpression[source, InputForm, HoldComplete], $Failed]];
  Replace[held, {
    HoldComplete[WorkRooms[w_Integer, h_Integer, t_Integer, f_Integer]] /;
      2 <= w <= 1024 && 2 <= h <= 1024 && 1 <= t <= 64 && 0 <= f <= 1000000 :>
      <|"protocol" -> "are.workrooms.v1", "width" -> w, "height" -> h,
        "tile" -> t, "frame" -> f,
        "coordinates" -> {"slot_x", "slot_y", "operation", "frame"},
        "stages" -> MapThread[<|"kind" -> #1, "color" -> #2|> &,
          {{"render", "raster", "msaa", "aa"}, {"green", "blue", "orange", "purple"}}]|>,
    _ :> $Failed}]
];
(* Sparse dependency witness, deliberately small. Million-room runtime uses
   implicit tiles and barriers instead of expanding an N-by-N dense matrix. *)
RoomWitness[] := Module[{nx = 2, ny = 2, nr = 4, nt, edges, g, remaining, fronts = {}, ready},
  nt = nx ny;
  edges = Join[
    Flatten[Table[DirectedEdge[r, nr + t], {r, nr}, {t, nt}]],
    Table[DirectedEdge[nr + t, nr + nt + t], {t, nt}],
    Flatten[Table[
      Table[DirectedEdge[nr + nt + (yy nx + xx + 1), nr + 2 nt + (y nx + x + 1)],
        {yy, Max[0, y - 1], Min[ny - 1, y + 1]}, {xx, Max[0, x - 1], Min[nx - 1, x + 1]}],
      {y, 0, ny - 1}, {x, 0, nx - 1}]],
    Table[DirectedEdge[nr + 2 nt + t, nr + 3 nt + 1], {t, nt}]];
  g = Graph[Range[nr + 3 nt + 1], edges]; remaining = VertexList[g];
  While[Length[remaining] > 0,
    ready = Pick[remaining, VertexInDegree[Subgraph[g, remaining]], 0];
    If[ready === {}, Return[$Failed]];
    AppendTo[fronts, ready]; remaining = Complement[remaining, ready]];
  <|"acyclic" -> AcyclicGraphQ[g], "matrixDimensions" -> Dimensions[AdjacencyMatrix[g]],
    "edgeCount" -> EdgeCount[g], "waveSizes" -> (Length /@ fronts),
    "workRooms" -> nr + 3 nt, "handoffNodes" -> 1|>
];
roomProbe = 0;
ExportString[<|"descriptor" -> ParseRoomPlan["WorkRooms[32,32,8,0]"],
  "witness" -> RoomWitness[],
  "heldAssignmentRejected" -> (ParseRoomPlan["WorkRooms[(roomProbe=1),32,8,0]"] === $Failed && roomProbe === 0),
  "unknownOperationRejected" -> (ParseRoomPlan["Run[\"anything\"]"] === $Failed),
  "budgetRejected" -> (ParseRoomPlan["WorkRooms[2048,32,8,0]"] === $Failed)|>, "RawJSON"]
