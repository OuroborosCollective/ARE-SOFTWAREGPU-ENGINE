(* Bounded probe of the user's room example. Numeric f64, not our f32 DSL. *)
ClearAll[roomState, ids, serial, parallel, matrix];
count = 1024;
ids = N[Range[count]];
roomState[id_Real] := Sin[id] * Cos[id];
{serialSeconds, serial} = AbsoluteTiming[Map[roomState, ids]];
{parallelSeconds, parallel} = AbsoluteTiming[
  TimeConstrained[Quiet[ParallelMap[roomState, ids, Method -> "CoarsestGrained"]], 10, $Failed]];
kernels = Quiet[Check[Kernels[], $Failed]];
kernelCount = If[ListQ[kernels], Length[kernels], Null];
matrix = Partition[serial, 32];
original = Table[N[Sin[i] * Cos[i]], {i, 32}];
ExportString[<|
  "protocol" -> "are.room-map-probe.v1", "count" -> count,
  "requested_in_user_example" -> 1000000,
  "original_heading_syntax_valid" -> SyntaxQ["### 3. Aggregation und mehrfarbige Visualisierung am Zielknoten"],
  "serial_seconds_single_probe" -> serialSeconds,
  "parallel_seconds_single_probe" -> parallelSeconds,
  "parallel_returned_list" -> ListQ[parallel], "parallel_kernel_count" -> kernelCount,
  "parallel_same_values" -> If[ListQ[parallel], SameQ[serial, parallel], Null],
  "machine_vs_original_max_abs_delta" -> Max[Abs[Take[serial, 32] - original]],
  "matrix_dimensions" -> Dimensions[matrix],
  "plot_head" -> ToString[Head[ArrayPlot[matrix, ColorFunction -> "TemperatureMap"]]],
  "displayed_values" -> Length[Flatten[matrix]],
  "true_parallelism_verified" -> (IntegerQ[kernelCount] && kernelCount > 0 && ListQ[parallel]),
  "performance_claim" -> "none: single provider probe, launch/fallback overhead included"
|>, "RawJSON"]
