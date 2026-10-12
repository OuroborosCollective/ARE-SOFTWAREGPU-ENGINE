ClearAll[neighbors, tileID, needed, simulate];
width=19; height=13; tile=5; nx=Ceiling[width/tile]; ny=Ceiling[height/tile]; nt=nx ny; primitives=4;
tileID[x_,y_]:=1+Quotient[Clip[y,{0,height-1}],tile] nx+Quotient[Clip[x,{0,width-1}],tile];
neighbors[i_]:=With[{x=Mod[i-1,nx],y=Quotient[i-1,nx]},Sort[Flatten[Table[If[0<=x+dx<nx && 0<=y+dy<ny,1+x+dx+(y+dy) nx,Nothing],{dy,-1,1},{dx,-1,1}]]]];
needed[i_]:=With[{x=Mod[i-1,nx] tile,y=Quotient[i-1,nx] tile},Union[Flatten[Table[tileID[px+dx,py+dy],{px,x,Min[x+tile,width]-1},{py,y,Min[y+tile,height]-1},{dx,-1,1},{dy,-1,1}]]]];
r=Range[primitives]; rt=primitives+Range[nt]; ms=primitives+nt+Range[nt]; aa=primitives+2 nt+Range[nt]; hand=primitives+3 nt+1;
edges=Join[Flatten[Table[DirectedEdge[a,b],{a,r},{b,rt}]],MapThread[DirectedEdge,{rt,ms}],Flatten[Table[DirectedEdge[ms[[j]],aa[[i]]],{i,nt},{j,neighbors[i]}]],DirectedEdge[#,hand]& /@ aa];
g=Graph[Range[hand],edges];
simulate[order_]:=Module[{pending=Length[neighbors[#]]& /@ Range[nt],finished=ConstantArray[False,nt],fired=ConstantArray[0,nt],early=False},
 Scan[Function[i,finished[[i]]=True;Scan[Function[j,pending[[j]]--;If[pending[[j]]==0,fired[[j]]++;If[!And@@finished[[neighbors[j]]],early=True]]],neighbors[i]]],order];
 And[!early,pending==ConstantArray[0,nt],fired==ConstantArray[1,nt]]];
SeedRandom[20261011]; checks=simulate[RandomSample[Range[nt]]]& /@ Range[100];
ExportString[<|"protocol"->"are.bio-workrooms.wolfram.v1","nodes"->VertexCount[g],"edges"->EdgeCount[g],"acyclic"->AcyclicGraphQ[g],"halo_matches_pixel_reads"->And@@Table[needed[i]==neighbors[i],{i,nt}],"resolve_permutations"->100,"single_release_after_all_neighbors"->And@@checks,"four_coordinates"->{"slot_x","slot_y","operation","frame"},"performance_evidence"->False|>,"RawJSON"]
