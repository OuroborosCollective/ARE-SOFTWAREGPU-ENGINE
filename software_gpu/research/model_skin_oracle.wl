(* Independent exact arithmetic check used by the native GLB test fixture.
   Execute in Wolfram Language; no Wolfram call is made inside a frame. *)
weights = Range[12]/78;
point = {1, 2, 3, 1};
joints = Table[{{1, 0, 0, j}, {0, 1, 0, 0},
                {0, 0, 1, 0}, {0, 0, 0, 1}}, {j, 12}];
allTwelve = Sum[weights[[j]] joints[[j]].point, {j, 12}];
firstFour = Sum[weights[[j]] joints[[j]].point, {j, 4}]/Total[Take[weights, 4]];
{allTwelve, firstFour, RotationMatrix[Pi/2, {0, 0, 1}].{1, 0, 0}}
(* {{28/3, 2, 3, 1}, {4, 2, 3, 1}, {0, 1, 0}} *)
